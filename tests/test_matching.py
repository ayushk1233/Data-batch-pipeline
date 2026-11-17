import copy
from datetime import date
from decimal import Decimal
import random
import unittest

from spend_pipeline.entities import resolve_entities
from spend_pipeline.matching import match_records


def record(rid, source="ledger", **changes):
    row = dict(record_id=rid, source=source, priority=0 if source == "ledger" else 1,
               include=True, exclusion_reason="", supplier_id="", supplier_name="Example Supply Limited",
               supplier_namespace=source, item_id="", item_namespace=source,
               description="Steel bolt M8", context="", po="4500012345", po_item="10", invoice="",
               invoice_line="", receipt="", receipt_item="", quantity=Decimal("2"),
               spend=Decimal("100"), date=None, uom="EA", reexports=False)
    row.update(changes)
    return row


def run(records, config=None):
    resolve_entities(records, config or {})
    stats = match_records(records, config or {})
    return records, stats


class EntityTests(unittest.TestCase):
    def test_legal_suffix_alias_is_anchored_to_unique_id(self):
        rows = [record("1", supplier_id="s1"), record("2", "invoices", supplier_name=" EXAMPLE Supply (Pty) Ltd. ")]
        resolve_entities(rows)
        self.assertEqual(rows[0]["supplier_key"], rows[1]["supplier_key"])

    def test_similar_suppliers_and_namespaced_ids_remain_distinct(self):
        rows = [record("1", supplier_id="s1"), record("2", supplier_name="Example Supplies Limited", supplier_id="s2"),
                record("3", "invoices", supplier_id="s1", supplier_name="")]
        resolve_entities(rows)
        self.assertEqual(3, len({r["supplier_key"] for r in rows}))

    def test_ambiguous_name_does_not_merge_distinct_ids(self):
        rows = [record("1", supplier_id="s1"), record("2", supplier_id="s2"), record("3", "invoices")]
        resolve_entities(rows)
        self.assertEqual(3, len({r["supplier_key"] for r in rows}))

    def test_material_alias_and_specification_separation(self):
        rows = [record("1", item_id="i1"), record("2", "invoices"), record("3", description="Steel bolt M10")]
        resolve_entities(rows)
        self.assertEqual(rows[0]["item_key"], rows[1]["item_key"])
        self.assertNotEqual(rows[0]["item_key"], rows[2]["item_key"])

    def test_unknown_entities_are_not_one_giant_group(self):
        rows = [record(str(i), supplier_name="", description="Parts") for i in range(4)]
        resolve_entities(rows)
        self.assertEqual(4, len({r["supplier_key"] for r in rows}))
        self.assertEqual(4, len({r["item_key"] for r in rows}))

    def test_excluded_rows_cannot_change_existing_aliases(self):
        base = [record("1", supplier_id="s1", item_id="i1"), record("2", "invoices")]
        left = copy.deepcopy(base)
        right = copy.deepcopy(base) + [record("3", supplier_id="s2", item_id="i2", include=False, exclusion_reason="CANCELLED")]
        resolve_entities(left)
        resolve_entities(right)
        self.assertEqual([(r["supplier_key"], r["item_key"]) for r in left],
                         [(r["supplier_key"], r["item_key"]) for r in right[:2]])

    def test_conflicting_explicit_item_specs_override_reused_id(self):
        rows = [record("1", item_id="i1"), record("2", item_id="i1", description="Steel bolt M10")]
        resolve_entities(rows)
        self.assertNotEqual(rows[0]["item_key"], rows[1]["item_key"])

    def test_input_root_does_not_affect_keys(self):
        left = [record("1", supplier_id="s", item_id="i")]
        right = copy.deepcopy(left)
        resolve_entities(left, {"input_root": "/first"})
        resolve_entities(right, {"input_root": "/second"})
        self.assertEqual(left, right)


class MatchingTests(unittest.TestCase):
    def test_one_to_one_match_normalizes_po_and_zero_padded_item(self):
        rows, stats = run([record("1", supplier_id="s", item_id="i"),
                           record("2", "invoices", po="PO:4500012345/00010", po_item="", invoice="inv99")])
        self.assertEqual(1, stats["cross_source_matches"])
        self.assertFalse(rows[1]["include"])
        self.assertEqual(Decimal("0"), rows[1]["spend"])
        self.assertEqual("1", rows[1]["duplicate_of"])
        self.assertEqual(rows[0]["supplier_key"], rows[1]["supplier_key"])
        self.assertEqual(rows[0]["item_key"], rows[1]["item_key"])

    def test_reexport_fingerprint_not_invoice_alone(self):
        rows, stats = run([record("1", "invoices", invoice="INV7", invoice_line="1", reexports=True),
                           record("2", "invoices", invoice="inv-7", invoice_line="1", reexports=True),
                           record("3", "invoices", invoice="INV7", invoice_line="2", reexports=True)])
        self.assertEqual(1, stats["reexports"])
        self.assertEqual(2, sum(r["include"] for r in rows))
        self.assertTrue(rows[2]["include"])

    def test_reexport_detection_requires_opt_in_and_invoice(self):
        rows, stats = run([record("1", "invoices", invoice="INV7"), record("2", "invoices", invoice="INV7"),
                           record("3", "invoices", reexports=True), record("4", "invoices", reexports=True)])
        self.assertEqual(0, stats["reexports"])
        self.assertTrue(all(r["include"] for r in rows))

    def test_repeat_receipts_and_ambiguous_counterpart_are_retained(self):
        rows, stats = run([record("1", receipt="receipt1"), record("2", receipt="receipt2"), record("3", "invoices")])
        self.assertTrue(all(r["include"] for r in rows))
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertGreater(stats["ambiguous"], 0)

    def test_two_legitimate_equal_purchases_with_distinct_po_lines(self):
        rows, stats = run([record("1", po_item="10"), record("2", po_item="20"),
                           record("3", "invoices", po_item="10"), record("4", "invoices", po_item="20")])
        self.assertEqual(2, stats["cross_source_matches"])
        self.assertEqual(Decimal("200"), sum(r["spend"] for r in rows if r["include"]))

    def test_excluded_record_cannot_suppress_valid_purchase(self):
        rows, stats = run([record("1", include=False, exclusion_reason="CANCELLED", spend=Decimal("0")),
                           record("2", "invoices")])
        self.assertTrue(rows[1]["include"])
        self.assertEqual(0, stats["cross_source_matches"])

    def test_excluded_reexport_cannot_consume_valid_row(self):
        rows, stats = run([record("1", "invoices", include=False, exclusion_reason="NOT_APPROVED", invoice="I", reexports=True),
                           record("2", "invoices", invoice="I", reexports=True)])
        self.assertTrue(rows[1]["include"])
        self.assertEqual(0, stats["reexports"])

    def test_supplier_item_quantity_and_sign_conflicts_prevent_removal(self):
        for changes in [{"supplier_name": "Unrelated Firm"}, {"description": "Steel bolt M10"},
                        {"quantity": Decimal("1")}, {"spend": Decimal("-100")}]:
            with self.subTest(changes=changes):
                rows, stats = run([record("1"), record("2", "invoices", **changes)])
                self.assertTrue(rows[1]["include"])
                self.assertEqual(0, stats["cross_source_matches"])

    def test_no_po_can_match_only_with_tight_date_and_identity(self):
        for days, expected in [(0, 1), (5, 1), (8, 0)]:
            rows, stats = run([record("1", po="", date=date(2026, 1, 1)),
                               record("2", "invoices", po="", date=date(2026, 1, 1 + days))])
            self.assertEqual(expected, stats["cross_source_matches"])
        rows, stats = run([record("1", po=""), record("2", "invoices", po="")])
        self.assertEqual(0, stats["cross_source_matches"])

    def test_bounded_candidate_block_keeps_uncertain_spend(self):
        rows = [record(str(i), receipt=str(i)) for i in range(120)] + [record("tool", "invoices")]
        rows, stats = run(rows, {"max_candidates": 50})
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertLessEqual(stats["candidate_comparisons"], 50)
        self.assertGreater(stats["candidate_limit"], 0)

    def test_shuffling_rows_preserves_decisions_and_groups(self):
        base = [record("1", supplier_id="s", item_id="i"), record("2", "invoices", invoice="X", reexports=True),
                record("3", "invoices", invoice="X", reexports=True), record("4", "invoices", po="different")]
        left, _ = run(copy.deepcopy(base))
        random.Random(90).shuffle(base)
        right, _ = run(copy.deepcopy(base))
        left_map = {r["record_id"]: r for r in left}
        right_map = {r["record_id"]: r for r in right}
        self.assertEqual(left_map, right_map)

    def test_integral_decimal_po_items_match_equivalent_references(self):
        for po, poi in [("4500012345/10.0", ""), ("4500012345/00010", ""), ("4500012345", "10")]:
            with self.subTest(po=po, poi=poi):
                rows, stats = run([record("1", po_item="10.0"), record("2", "invoices", po=po, po_item=poi)])
                self.assertEqual(1, stats["cross_source_matches"])

    def test_conflicting_explicit_receipts_preserve_distinct_purchases(self):
        for changes in [{"receipt": "receipt2"}, {"receipt_item": "2"}]:
            with self.subTest(changes=changes):
                rows, stats = run([record("1", receipt="receipt1", receipt_item="1"),
                                   record("2", "invoices", **dict({"receipt":"receipt1", "receipt_item":"1"}, **changes))])
                self.assertEqual(0, stats["cross_source_matches"])
                self.assertEqual(Decimal("200"), sum(r["spend"] for r in rows))

    def test_conflicting_invoice_lines_preserve_distinct_purchases(self):
        rows, stats = run([record("1", invoice="INV7", invoice_line="1"),
                           record("2", "invoices", invoice="INV7", invoice_line="2")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertEqual(Decimal("200"), sum(r["spend"] for r in rows))

    def test_conflicting_reliable_supplier_ids_defeat_name_similarity(self):
        rows, stats = run([record("1", supplier_id="s1", supplier_namespace="shared"),
                           record("2", "invoices", supplier_id="s2", supplier_namespace="shared")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertTrue(all(r["include"] for r in rows))

    def test_relative_amount_closeness_is_not_identity_by_default(self):
        rows, stats = run([record("1", spend=Decimal("100000"), invoice="first"),
                           record("2", "invoices", spend=Decimal("100050"), invoice="second")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertEqual(Decimal("200050"), sum(r["spend"] for r in rows))

    def test_close_ocr_supplier_word_can_match_with_other_evidence(self):
        rows, stats = run([record("1", supplier_name="Ferro Components Ltd"),
                           record("2", "invoices", supplier_name="Ferro Cornponents Limited")])
        self.assertEqual(1, stats["cross_source_matches"])
        self.assertFalse(rows[1]["include"])

    def test_ordered_dimensions_are_not_an_unordered_number_set(self):
        rows, stats = run([record("1", description="Steel plate 10x20"),
                           record("2", "invoices", description="Steel plate 20x10")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertEqual(Decimal("200"), sum(r["spend"] for r in rows))

    def test_supplier_name_word_reordering_keeps_supported_match(self):
        rows, stats = run([record("1", supplier_name="Ferro Industrial Components Ltd"),
                           record("2", "invoices", supplier_name="Industrial Ferro Components Limited")])
        self.assertEqual(1, stats["cross_source_matches"])

    def test_shared_long_name_prefix_does_not_hide_distinct_tokens(self):
        rows, stats = run([record("1", supplier_name="Example Pumps East Ltd", invoice="first"),
                           record("2", "invoices", supplier_name="Example Pumps West Ltd", invoice="second")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertEqual(Decimal("200"), sum(r["spend"] for r in rows))

    def test_reference_prefix_does_not_eat_real_identifier_letters(self):
        rows, stats = run([record("1", po="PORT9000"), record("2", "invoices", po="RT9000")])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertTrue(all(r["include"] for r in rows))

    def test_same_priority_sources_never_arbitrarily_win(self):
        rows, stats = run([record("1", "alpha", priority=0), record("2", "beta", priority=0)])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertTrue(all(r["include"] for r in rows))

    def test_zero_value_and_generic_text_are_not_automatic_duplicates(self):
        rows, stats = run([record("1", po="", description="Parts", spend=Decimal("0")),
                           record("2", "invoices", po="", description="Parts", spend=Decimal("0"))])
        self.assertEqual(0, stats["cross_source_matches"])
        self.assertTrue(all(r["include"] for r in rows))


if __name__ == "__main__":
    unittest.main()
