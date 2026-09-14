import unittest

from app.services.evaluation import build_sentence_records, count_article_words


class SentenceCitationTests(unittest.TestCase):
    def test_citations_before_or_after_punctuation_attach_to_the_same_claim(self):
        body = (
            "First fact [S1-F1]. Second fact. [S1-F2] "
            "Third fact. [S1-F3][S1-F4]"
        )
        records = build_sentence_records(body)
        self.assertEqual(len(records), 3)
        self.assertEqual(
            [record["citation_ids"] for record in records],
            [["S1-F1"], ["S1-F2"], ["S1-F3", "S1-F4"]],
        )
        self.assertEqual([record["sentence_index"] for record in records], [0, 1, 2])

    def test_us_abbreviation_does_not_split_sentence(self):
        records = build_sentence_records(
            "SK Hynix debuted in the U.S. market [S1-F1]. "
            "Its shares rose [S1-F2]."
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["citation_ids"], ["S1-F1"])
        self.assertIn("U.S. market", records[0]["sentence_text"])

    def test_uncited_claim_remains_uncited_and_word_count_ignores_labels(self):
        records = build_sentence_records(
            "An uncited claim. A supported claim [S1-F1]."
        )
        self.assertEqual(records[0]["citation_ids"], [])
        self.assertEqual(records[1]["citation_ids"], ["S1-F1"])
        self.assertEqual(count_article_words("<b>First</b> fact [S1-F1]."), 2)


if __name__ == "__main__":
    unittest.main()
