import collections
from django.db import ProgrammingError

from .conf import settings
from .fields import JsonCharField
from .forms import BaseForm
from .validators import validate_no_underscore


class JsonStructure:
    """
    Set json-fields as model properties so they can be retrieved easily.
        
    Usage:
    - a single underscore is reserved for the property name, so use CamelCase
      for form keywords and field names.
    """

    def __init__(self, model_class):
        # setup instance variables
        self.model_class = model_class
        self.properties = []
        self.forms = collections.OrderedDict()
        self.set_forms()
        self.prepare_properties()

    def set_forms(self) -> None:
        """
        Set forms with meta attributes based on form_structure.
        """
        for keyword, form in self.form_list:
            validate_no_underscore(keyword)
            self.forms[keyword] = form

    def prepare_properties(self) -> None:
        for keyword, form in self.forms.items():
            self._prepare_json_properties(keyword=keyword, form=form)
            self._prepare_repeating_fields_properties(keyword=keyword, form=form)

    def update_properties(self) -> None:
        """
        Update the model properties after each save, as the number of repeating
        field is depending on the length of the data.
        """
        # Remove old properties first
        self.properties = []
        for keyword, form in self.forms.items():
            self._prepare_json_properties(keyword=keyword, form=form)
            self._prepare_repeating_fields_properties(keyword=keyword, form=form)

    def _prepare_json_properties(self, keyword: str, form):
        for name, field, is_json in form.model_fields():
            if is_json:
                property_name = '{keyword}{delimiter}{name}'.format(
                    keyword=keyword,
                    delimiter=settings.FLEXIFORM_MODEL_JSON_PROPERTIES_DELIMITER,
                    name=name
                )
                self._set_property_for_dict(
                    property_name=property_name,
                    field=field,
                    keyword=keyword,
                    name=name
                )

    def _set_property_for_dict(self, property_name: str, field: JsonCharField,
                               keyword: str, name: str) -> None:
        """
        Define one property per field, and set it on the model.
        """
        def property_fn(obj):
            if obj.data:
                return field.from_json(data=obj.data.get(keyword, {}), name=name)
            return ''

        self.properties.append(property_name)
        setattr(
            self.model_class,
            property_name,
            property(property_fn)
        )

    def _prepare_repeating_fields_properties(self, keyword: str, form):
        """
        Repeating fields are 'exploded' into one column per value. The number
        of columns is defined by the longest list of repeating fields.
        """
        if hasattr(form.Meta, 'repeating_fields'):
            for field in form.Meta.repeating_fields:
                field_lengths = self._get_repeating_field_lengths(
                    keyword=keyword, name=field.name
                )
                # If the database is empty, self._get_repeating_field_lengths
                # does not return anything. Prevent errors by setting a
                # max_length manually.
                try:
                    max_length = max(field_lengths)
                except ValueError:
                    max_length = 0
                self._set_nested_properties(
                    keyword=keyword,
                    field=field,
                    max_length=max_length
                )

    def _get_repeating_field_lengths(self, keyword: str, name: str):
        """
        Generator for list-lengths of given field_path
        """
        try:
            rows = self.model_class.objects.exclude(data__isnull=True).only('data')
            for row in rows:
                yield len(row.data.get(keyword, {}).get(name, []))
        except ProgrammingError:
            yield 0

    def _set_nested_properties(self, keyword: str, field, max_length: int):
        """
        Set one property per row, repeating this max_length times. E.g.
        <keyword>_<repeating_field_name>_<first_field>_0
        <keyword>_<repeating_field_name>_<second_field>_0
        <keyword>_<repeating_field_name>_<first_field>_1
        <keyword>_<repeating_field_name>_<second_field>_1
        """
        for i in range(0, max_length):
            for key in field.row.keys():
                property_name = f'{keyword}_{field.name}_{key}_{i}'
                self._set_property_for_list(
                    keyword, field, key, property_name, i)

    def _set_property_for_list(
            self, keyword, field, row_index, property_name, i):
        def property_fn(obj):
            try:
                return obj.data[keyword][field.name][i][row_index]
            except (IndexError, KeyError, AttributeError):
                return ''

        self.properties.append(property_name)
        setattr(
            self.model_class,
            property_name,
            property(property_fn)
        )


class AutoSpawn:
    """
    Create an instance for all decorated forms
    """
    _structures = []

    def register(self, form: BaseForm):
        self._structures.append(form)

    def start(self):
        for item in self._structures:
            item.structure(model_class=item.Meta.model)

auto_spawn = AutoSpawn()
