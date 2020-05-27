import random
from functools import lru_cache
from datetime import date, datetime
import dateutil.parser
from ast import literal_eval

from typing import Optional, Union, List, Tuple

from faker import Faker

from .data_gen_exceptions import DataGenError

import snowfakery.data_generator_runtime  # noqa
from snowfakery.plugins import SnowfakeryPlugin, PluginContext, lazy

FieldDefinition = "snowfakery.data_generator_runtime_dom.FieldDefinition"
ObjectRow = "snowfakery.data_generator_runtime.ObjectRow"

fake = Faker()

# It might make more sense to use context vars for context handling when
# Python 3.6 is out of the support matrix.


def parse_weight_str(context: PluginContext, weight_value) -> int:
    """For constructs like:

    - choice:
        probability: 60%
        pick: Closed Won

    Render and convert the 60% to just 60.
    """
    weight_str = context.evaluate(weight_value)
    if isinstance(weight_str, str):
        weight_str = weight_str.rstrip("%")
    return int(weight_str)


def weighted_choice(choices: List[Tuple[int, object]]):
    """Selects from choices based on their weights"""
    weights = [weight for weight, value in choices]
    options = [value for weight, value in choices]
    return random.choices(options, weights, k=1)[0]


@lru_cache(maxsize=512)
def parse_date(d: Union[str, datetime, date]) -> Optional[Union[datetime, date]]:
    if isinstance(d, (datetime, date)):
        return d
    try:
        return dateutil.parser.parse(d)
    except dateutil.parser.ParserError:
        pass


def render_boolean(context: PluginContext, value: FieldDefinition) -> bool:
    val = context.evaluate(value)
    if isinstance(val, str):
        val = literal_eval(val)

    return bool(val)


class StandardFuncs(SnowfakeryPlugin):
    class Functions:
        int = int

        def date(
            self, *, year: Union[str, int], month: Union[str, int], day: Union[str, int]
        ):
            """A YAML-embeddable function to construct a date from strings or integers"""
            return date(year, month, day)

        def datetime(
            self,
            *,
            year: Union[str, int],
            month: Union[str, int],
            day: Union[str, int],
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ):
            """A YAML-embeddable function to construct a datetime from strings or integers"""
            return datetime(year, month, day, hour, minute, second, microsecond)

        def date_between(self, *, start_date, end_date):
            """A YAML-embeddable function to pick a date between two ranges"""
            start_date = parse_date(start_date) or start_date
            end_date = parse_date(end_date) or end_date
            try:
                return fake.date_between(start_date, end_date)
            except ValueError as e:
                if "empty range" not in str(e):
                    raise
            # swallow empty range errors per Python conventions

        def i18n_fake(self, locale: str, fake: str):
            faker = Faker(locale)
            func = getattr(faker, fake)
            return func()

        def random_number(self, min: int, max: int) -> int:
            """Pick a random number between min and max like Python's randint."""
            return random.randint(min, max)

        def reference(self, x: Union[ObjectRow, str]):
            """YAML-embeddable function to Reference another object."""
            if hasattr(x, "id"):  # reference to an object with an id
                target = x
            elif isinstance(x, str):  # name of an object
                obj = self.context.field_vars()[x]
                if not getattr(obj, "id"):
                    raise DataGenError(
                        f"Reference to incorrect object type {obj}", None, None
                    )
                target = obj
            else:
                raise DataGenError(
                    f"Can't get reference to object of type {type(x)}: {x}", None, None
                )

            return target

        @lazy
        def random_choice(self, *choices):
            """Template helper for random choices.

            Supports structures like this:

            random_choice:
                - a
                - b
                - ${{c}}

            Or like this:

            random_choice:
                - choice:
                    pick: A
                    probability: 50%
                - choice:
                    pick: A
                    probability: 50%

            Probabilities are really just weights and don't need to
            add up to 100.

            Pick-items can have arbitrary internal complexity.

            Pick-items are lazily evaluated.
            """
            if not choices:
                raise ValueError("No choices supplied!")

            if getattr(choices[0], "function_name", None) == "choice":
                choices = [self.context.evaluate(choice) for choice in choices]
                rc = weighted_choice(choices)
            else:
                rc = random.choice(choices)
            if hasattr(rc, "render"):
                rc = self.context.evaluate(rc)
            return rc

        @lazy
        def choice(
            self,
            pick,
            probability: FieldDefinition = None,
            when: FieldDefinition = None,
        ):
            """Supports the choice: sub-items used in `random_choice` or `if`"""
            if probability:
                probability = parse_weight_str(self.context, probability)
            return probability or when, pick

        @lazy
        def if_(self, *choices: FieldDefinition):
            """Template helper for conditional choices.

            Supports structures like this:

            if:
                - choice:
                    when: ${{something}}
                    pick: A
                - choice:
                    when: ${{something}}
                    pick: B

            Pick-items can have arbitrary internal complexity.

            Pick-items are lazily evaluated.
            """
            if not choices:
                raise ValueError("No choices supplied!")

            choices = [self.context.evaluate(choice) for choice in choices]
            for when, choice in choices[:-1]:
                if when is None:
                    raise SyntaxError(
                        "Every choice except the last one should have a when-clause"
                    )
            true_choices = (
                choice
                for when, choice in choices
                if when and render_boolean(self.context, when)
            )
            rc = next(true_choices, choices[-1][-1])  # default to last choice
            if hasattr(rc, "render"):
                rc = self.context.evaluate(rc)
            return rc

    setattr(Functions, "if", Functions.if_)
