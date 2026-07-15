import json
from dataclasses import dataclass

import requests
from youtube_transcript_api import YouTubeTranscriptApi


@dataclass(frozen=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str


def _parse_initial_data(page_html: str) -> dict:
    decoder = json.JSONDecoder()

    for marker in (
        "var ytInitialData = ",
        'window["ytInitialData"] = ',
    ):
        marker_index = page_html.find(marker)
        if marker_index == -1:
            continue

        json_index = page_html.find("{", marker_index + len(marker))
        if json_index == -1:
            continue

        initial_data, _ = decoder.raw_decode(page_html[json_index:])
        return initial_data

    raise ValueError("YouTube page did not contain ytInitialData.")


def _find_first_video_renderer(value) -> dict | None:
    if isinstance(value, dict):
        renderer = value.get("videoRenderer")
        if isinstance(renderer, dict):
            return renderer

        for child in value.values():
            renderer = _find_first_video_renderer(child)
            if renderer is not None:
                return renderer

    if isinstance(value, list):
        for child in value:
            renderer = _find_first_video_renderer(child)
            if renderer is not None:
                return renderer

    return None


def _video_title(renderer: dict) -> str:
    title = renderer.get("title", {})
    if title.get("simpleText"):
        return title["simpleText"]

    return "".join(
        run.get("text", "")
        for run in title.get("runs", [])
    ).strip()


def get_newest_video(channel_videos_url: str) -> YouTubeVideo | None:
    """Returns only the first long-form upload exposed by a videos page."""
    try:
        response = requests.get(
            channel_videos_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()

        renderer = _find_first_video_renderer(_parse_initial_data(response.text))
        if renderer is None or not renderer.get("videoId"):
            return None

        video_id = renderer["videoId"]
        return YouTubeVideo(
            video_id=video_id,
            title=_video_title(renderer),
            url=f"https://www.youtube.com/watch?v={video_id}",
        )

    except Exception as error:
        print(
            "Oops, couldn't find the newest video from "
            f"{channel_videos_url}. Error: {error}"
        )
        return None


def get_video_transcript(video_id: str) -> str | None:
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.fetch(video_id)

        full_text = ""
        for chunk in transcript_list:
            full_text += chunk.text + " "

        return full_text.strip()

    except Exception as e:
        print(f"Oops, couldn't get transcript for this video: {video_id}. Error: {e}")
        return None
