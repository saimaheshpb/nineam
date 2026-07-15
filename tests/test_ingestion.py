import json
import unittest
from unittest.mock import Mock, call, patch

from app.config import NewsSource, RSS_SOURCES, YOUTUBE_SOURCE
from app.scrapers.youtube import YouTubeVideo, get_newest_video
from main import EvidenceExtractionCallPacer, run_ingestion


EXPECTED_RSS_URLS = [
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://huggingface.co/blog/feed.xml",
    "https://bair.berkeley.edu/blog/feed.xml",
    "https://thegradient.pub/rss/",
]


def database_mocks():
    connection = Mock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = None
    return connection, cursor


class SourceSelectionTests(unittest.TestCase):
    def test_exactly_two_entries_are_requested_from_each_configured_feed(self):
        connection, _ = database_mocks()

        with (
            patch("main.setup_database"),
            patch("main.connect_database", return_value=connection),
            patch("main.get_latest_urls", return_value=[]) as latest_urls,
            patch("main.get_newest_video", return_value=None) as newest_video,
        ):
            run_ingestion(pacer=Mock())

        self.assertEqual(
            [source.url for source in RSS_SOURCES],
            EXPECTED_RSS_URLS,
        )
        self.assertEqual(
            latest_urls.call_args_list,
            [call(url, 2) for url in EXPECTED_RSS_URLS],
        )
        newest_video.assert_called_once_with(YOUTUBE_SOURCE.url)

    def test_unavailable_newest_transcript_does_not_try_an_older_video(self):
        connection, _ = database_mocks()
        newest = YouTubeVideo(
            video_id="newest-id",
            title="Newest upload",
            url="https://www.youtube.com/watch?v=newest-id",
        )

        with (
            patch("main.setup_database"),
            patch("main.connect_database", return_value=connection),
            patch("main.get_latest_urls", return_value=[]),
            patch("main.get_newest_video", return_value=newest) as newest_video,
            patch("main.get_video_transcript", return_value=None) as transcript,
            patch("main.extract_structured_data") as extract,
        ):
            pacer = Mock()
            run_ingestion(pacer=pacer)

        newest_video.assert_called_once_with(YOUTUBE_SOURCE.url)
        transcript.assert_called_once_with("newest-id")
        pacer.before_call.assert_not_called()
        extract.assert_not_called()

    def test_newest_transcript_is_stored_as_the_primetime_evidence(self):
        connection, cursor = database_mocks()
        newest = YouTubeVideo(
            video_id="newest-id",
            title="Newest upload",
            url="https://www.youtube.com/watch?v=newest-id",
        )
        structured_data = {
            "headline": "Structured headline",
            "summary": "Structured summary",
            "entities": [],
            "key_facts": [],
            "category": "technology",
            "importance_score": 7,
        }

        with (
            patch("main.setup_database"),
            patch("main.connect_database", return_value=connection),
            patch("main.get_latest_urls", return_value=[]),
            patch("main.get_newest_video", return_value=newest),
            patch("main.get_video_transcript", return_value="Video transcript"),
            patch("main.extract_structured_data", return_value=structured_data),
            patch("main.get_embedding", return_value=[0.1, 0.2]),
            patch("main.find_semantic_match", return_value=None),
        ):
            pacer = Mock()
            run_ingestion(pacer=pacer)

        pacer.before_call.assert_called_once_with()
        insert_parameters = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(
            insert_parameters[:6],
            (
                newest.url,
                "ThePrimeTime",
                "technology",
                "Structured headline",
                "Structured summary",
                "Video transcript",
            ),
        )
        connection.commit.assert_called_once_with()


class EvidenceExtractionPacingTests(unittest.TestCase):
    def test_seven_extraction_attempts_use_evaluation_equivalent_pacing(self):
        sources = [
            NewsSource(f"Source {index}", f"https://feed{index}.example", "ai")
            for index in range(4)
        ]
        links_by_feed = {
            sources[0].url: ["https://story.example/1", "https://story.example/2"],
            sources[1].url: ["https://story.example/3", "https://story.example/4"],
            sources[2].url: ["https://story.example/5", "https://story.example/6"],
            sources[3].url: ["https://story.example/7"],
        }
        connection, _ = database_mocks()
        sleep = Mock()
        pacer = EvidenceExtractionCallPacer(sleep_fn=sleep)

        with (
            patch("main.RSS_SOURCES", sources),
            patch("main.setup_database"),
            patch("main.connect_database", return_value=connection),
            patch(
                "main.get_latest_urls",
                side_effect=lambda url, _limit: links_by_feed[url],
            ),
            patch("main.get_article_text", return_value="Article text"),
            patch("main.extract_structured_data", return_value={}) as extract,
            patch("main.get_newest_video", return_value=None),
        ):
            run_ingestion(pacer=pacer)

        self.assertEqual(extract.call_count, 7)
        self.assertEqual(
            sleep.call_args_list,
            [call(20), call(20), call(60), call(20), call(20), call(60)],
        )


class YouTubeDiscoveryTests(unittest.TestCase):
    @patch("app.scrapers.youtube.requests.get")
    def test_only_first_video_renderer_is_returned(self, get):
        initial_data = {
            "contents": [
                {
                    "videoRenderer": {
                        "videoId": "newest-id",
                        "title": {"runs": [{"text": "Newest upload"}]},
                    }
                },
                {
                    "videoRenderer": {
                        "videoId": "older-id",
                        "title": {"runs": [{"text": "Older upload"}]},
                    }
                },
            ]
        }
        get.return_value.text = (
            "<script>var ytInitialData = "
            f"{json.dumps(initial_data)};"
            "</script>"
        )

        video = get_newest_video(YOUTUBE_SOURCE.url)

        self.assertEqual(
            video,
            YouTubeVideo(
                video_id="newest-id",
                title="Newest upload",
                url="https://www.youtube.com/watch?v=newest-id",
            ),
        )
        get.assert_called_once_with(
            YOUTUBE_SOURCE.url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )


if __name__ == "__main__":
    unittest.main()
