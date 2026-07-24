import unittest
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from app.core.money import (
    MONEY_MAX,
    money_subtotal,
    money_to_json,
    normalize_money,
    quantize_money,
    sum_money,
)
from app.main import app
from app.schemas.dish import DishCreate


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class MoneyPolicyTests(unittest.TestCase):
    def test_half_up_rounding_is_centralized(self):
        self.assertEqual(quantize_money("1.005"), Decimal("1.01"))
        self.assertEqual(quantize_money("1.004"), Decimal("1.00"))

    def test_decimal_addition_and_subtotal_do_not_use_binary_float_math(self):
        self.assertEqual(sum_money(("0.1", "0.2")), Decimal("0.30"))
        self.assertEqual(money_subtotal("0.10", 3), Decimal("0.30"))

    def test_negative_non_finite_excess_scale_and_range_are_rejected(self):
        invalid_values = (
            "-0.01",
            "NaN",
            "Infinity",
            "-Infinity",
            "1.234",
            str(MONEY_MAX + Decimal("0.01")),
        )
        for value in invalid_values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_money(value)

    def test_trailing_zeroes_null_and_json_format_are_stable(self):
        self.assertEqual(normalize_money("10.500"), Decimal("10.50"))
        self.assertIsNone(normalize_money(None, nullable=True))
        self.assertEqual(money_to_json(Decimal("10.5")), "10.50")

    def test_dish_schema_uses_decimal_and_preserves_nullable_price(self):
        payload = {
            "name": "Schema dish",
            "description": "",
            "ingredients": "",
            "allergens": "",
            "image": "",
            "category_id": 1,
        }
        without_price = DishCreate.model_validate(payload)
        with_price = DishCreate.model_validate({**payload, "price": "12.30"})

        self.assertIsNone(without_price.price)
        self.assertEqual(with_price.price, Decimal("12.30"))
        self.assertEqual(
            with_price.model_dump(mode="json")["price"],
            "12.30",
        )
        with self.assertRaises(ValidationError):
            DishCreate.model_validate({**payload, "price": "12.301"})

    def test_frontend_only_formats_backend_money(self):
        waiter_script = (
            PROJECT_ROOT / "app/static/js/waiter.js"
        ).read_text(encoding="utf-8")
        menu_script = (
            PROJECT_ROOT / "app/static/js/app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("formatMoney(order.total_amount)", waiter_script)
        self.assertIn("formatMoney(line.subtotal)", waiter_script)
        self.assertIn("formatPrice(dish.price)", menu_script)
        self.assertIn('style: "currency"', waiter_script)
        self.assertIn('style: "currency"', menu_script)
        self.assertIn("minimumFractionDigits: 2", waiter_script)
        self.assertIn("maximumFractionDigits: 2", waiter_script)
        self.assertIn("minimumFractionDigits: 2", menu_script)
        self.assertIn("maximumFractionDigits: 2", menu_script)
        self.assertNotIn("parseFloat", waiter_script)
        self.assertNotIn(".toFixed(", waiter_script)

    def test_openapi_documents_decimal_inputs_and_string_outputs(self):
        schema = app.openapi()
        components = schema["components"]["schemas"]
        order_line_price = components["OrderLineRead"]["properties"][
            "unit_price"
        ]
        order_total = components["OrderRead"]["properties"]["total_amount"]
        dish_input = components["DishPriceUpdate"]["properties"]["price"]

        self.assertEqual(order_line_price["type"], "string")
        self.assertEqual(order_total["type"], "string")
        self.assertTrue(
            {"number", "string"}.issubset(
                {
                    option["type"]
                    for option in dish_input["anyOf"]
                    if option["type"] != "null"
                }
            )
        )
        self.assertIn(
            "/api/restaurants/{restaurant_id}/dishes/{dish_id}/price",
            schema["paths"],
        )
