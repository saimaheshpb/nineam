from youtube_transcript_api import YouTubeTranscriptApi


def get_video_transcript(video_id: str) -> str:
    try:
        api = YouTubeTranscriptApi()
        transcript_list = api.fetch(video_id)

        full_text = ""
        for chunk in transcript_list:
            full_text += chunk.text + " "

        return full_text.strip()

    except Exception as e:
        print(f"Oops, couldn't get transcript for this video: {video_id}. Error: {e}")
