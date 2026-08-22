#!/usr/bin/env python3
"""Build Lattice's checked-in catalog of free, embeddable lecture videos.

The catalog stores links and metadata only. Video bytes remain on the official
publisher's YouTube channel. MIT OpenCourseWare courses are discovered from
MIT's public search API and course pages; a small set of additional official
course playlists fills important curriculum gaps.

This refresh command requires yt-dlp, but Lattice does not::

    python3 -m pip install yt-dlp
    python3 scripts/build_video_catalog.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "lectures" / "catalog.json"
MIT_SEARCH_API = "https://open.mit.edu/api/v0/search/"
USER_AGENT = "CS-Library-Video-Catalog/1.0"
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_EMBED = re.compile(
    r"(?:img\.youtube\.com/vi/|youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=|live/)|youtu\.be/)"
    r"(?P<id>[A-Za-z0-9_-]{11})"
)
PLAYLIST_LINK = re.compile(r"(?:playlist\?list=|[?&]list=)(?P<id>[A-Za-z0-9_-]+)")
TAG = re.compile(r"<[^>]+>")
OFFICIAL_EMBED_OVERRIDES = {
    # The current CS50x Lecture 0 rejects YouTube's privacy-enhanced iframe,
    # while CS50's own frameable player serves the same official video.
    "UuIEbpQms8o": "https://video.cs50.io/UuIEbpQms8o",
}


# These are EECS cross-lists whose videos are useful engineering material but
# outside this computer-science shelf's scope. Courses without YouTube embeds
# are omitted automatically even when OCW labels them as having lecture video.
MIT_EXCLUDED_TITLES = frozenset(
    {
        "Control of Manufacturing Processes (SMA 6303)",
        "Engineering Innovation and Design",
        "Power Electronics",
        "Teaching College-Level Science and Engineering",
    }
)


PLAYLIST_COURSES: tuple[dict[str, Any], ...] = (
    {
        "id": "mit-6-004-spring-2017",
        "title": "Computation Structures",
        "code": "MIT 6.004",
        "institution": "MIT OpenCourseWare",
        "instructors": ["Prof. Chris Terman"],
        "term": "Spring 2017",
        "level": "Undergraduate",
        "subject": "Systems & Security",
        "stage": 4,
        "description": "Digital systems from logic gates through processors, memory, compilation, operating systems, and concurrency.",
        "sourceUrl": "https://ocw.mit.edu/courses/6-004-computation-structures-spring-2017/",
        "playlistId": "PLUl4u3cNGP62WVs95MNq3dQBqY2vGOtQ2",
        "license": "CC BY-NC-SA 4.0 (MIT OCW)",
        "featured": True,
    },
    {
        "id": "mit-6-824-spring-2020",
        "title": "Distributed Systems",
        "code": "MIT 6.824",
        "institution": "MIT",
        "instructors": ["Prof. Robert Morris"],
        "term": "Spring 2020",
        "level": "Graduate",
        "subject": "Systems & Security",
        "stage": 4,
        "description": "Fault tolerance, replication, consistency, distributed storage, and systems case studies.",
        "sourceUrl": "https://pdos.csail.mit.edu/6.824/2020/schedule.html",
        "playlistId": "PLrw6a1wE39_tb2fErI4-WkMbsvGQk9_UB",
        "license": "Free official course stream; source terms apply",
        "featured": True,
    },
    {
        "id": "mit-6-4210-fall-2022",
        "title": "Robotic Manipulation",
        "code": "MIT 6.4210",
        "institution": "MIT",
        "instructors": ["Prof. Russ Tedrake"],
        "term": "Fall 2022",
        "level": "Undergraduate / Graduate",
        "subject": "Robotics",
        "stage": 9,
        "description": "Perception, kinematics, motion planning, control, and learning for autonomous manipulation.",
        "sourceUrl": "https://manipulation.csail.mit.edu/Fall2022/schedule.html",
        "playlistId": "PLkx8KyIQkMfUSDs2hvTWzaq-cxGl8Ha69",
        "license": "Free official course stream; source terms apply",
        "featured": False,
    },
    {
        "id": "mit-6-832-spring-2022",
        "title": "Underactuated Robotics",
        "code": "MIT 6.832",
        "institution": "MIT",
        "instructors": ["Prof. Russ Tedrake"],
        "term": "Spring 2022",
        "level": "Graduate",
        "subject": "Robotics",
        "stage": 9,
        "description": "Nonlinear dynamics and control for walking, flying, and other underactuated robots.",
        "sourceUrl": "https://underactuated.csail.mit.edu/Spring2022/",
        "playlistId": "PLkx8KyIQkMfXyKku6DstXjD9xU93ptDyc",
        "license": "Free official course stream; source terms apply",
        "featured": False,
    },
    {
        "id": "mit-18-s191-fall-2020",
        "title": "Introduction to Computational Thinking",
        "code": "MIT 18.S191",
        "institution": "MIT OpenCourseWare",
        "instructors": ["Prof. Alan Edelman", "Prof. David Sanders", "Grant Sanderson"],
        "term": "Fall 2020",
        "level": "Undergraduate",
        "subject": "Mathematics",
        "stage": 2,
        "description": "Computation as a way to understand modeling, algorithms, data, images, climate, and uncertainty.",
        "sourceUrl": "https://ocw.mit.edu/courses/18-s191-introduction-to-computational-thinking-fall-2020/",
        "playlistId": "PLP8iPy9hna6Q2Kr16aWPOKE0dz9OnsnIJ",
        "license": "CC BY-NC-SA 4.0 (MIT OCW)",
        "featured": False,
    },
    {
        "id": "mit-6-s191-archive",
        "title": "Introduction to Deep Learning",
        "code": "MIT 6.S191",
        "institution": "MIT",
        "instructors": ["Alexander Amini", "Ava Soleimany"],
        "term": "Multi-year archive",
        "level": "Undergraduate / Graduate",
        "subject": "AI & Machine Learning",
        "stage": 8,
        "description": "Deep learning foundations and applications, with recurring annual lectures and guest sessions.",
        "sourceUrl": "https://introtodeeplearning.com/",
        "playlistId": "PLtBw6njQRU-rwp5__7C0oIVt26ZgjG9NI",
        "license": "Free official course stream; course materials use the MIT license",
        "featured": True,
    },
    {
        "id": "cmu-15-445-fall-2024",
        "title": "Introduction to Database Systems",
        "code": "CMU 15-445/645",
        "institution": "Carnegie Mellon University",
        "instructors": ["Prof. Andy Pavlo"],
        "term": "Fall 2024",
        "level": "Undergraduate / Graduate",
        "subject": "Databases",
        "stage": 4,
        "description": "Storage, indexing, query processing, concurrency control, recovery, and distributed databases.",
        "sourceUrl": "https://15445.courses.cs.cmu.edu/fall2024/",
        "playlistId": "PLSE8ODhjZXjYDBpQnSymaectKjxCy6BYq",
        "license": "Free official course stream; source terms apply",
        "featured": True,
    },
    {
        "id": "cmu-15-721-spring-2024",
        "title": "Advanced Database Systems",
        "code": "CMU 15-721",
        "institution": "Carnegie Mellon University",
        "instructors": ["Prof. Andy Pavlo"],
        "term": "Spring 2024",
        "level": "Graduate",
        "subject": "Databases",
        "stage": 7,
        "description": "Modern database internals, architecture, implementation techniques, and research systems.",
        "sourceUrl": "https://15721.courses.cs.cmu.edu/spring2024/",
        "playlistId": "PLSE8ODhjZXjYa_zX-KeMJui7pcN1rIaIJ",
        "license": "Free official course stream; source terms apply",
        "featured": False,
    },
    {
        "id": "missing-semester-2026",
        "title": "The Missing Semester of Your CS Education",
        "code": "MIT IAP",
        "institution": "MIT",
        "instructors": ["Missing Semester teaching team"],
        "term": "IAP 2026",
        "level": "All levels",
        "subject": "Software Practice",
        "stage": 1,
        "description": "Shells, development environments, debugging, version control, shipping code, agents, and code quality.",
        "sourceUrl": "https://missing.csail.mit.edu/2026/",
        "playlistId": "PLyzOVJj3bHQunmnnTXrNbZnBaCA-ieK4L",
        "license": "CC BY-NC-SA 4.0",
        "featured": True,
    },
    {
        "id": "missing-semester-2020",
        "title": "The Missing Semester — Classic Track",
        "code": "MIT IAP",
        "institution": "MIT",
        "instructors": ["Missing Semester teaching team"],
        "term": "IAP 2020",
        "level": "All levels",
        "subject": "Software Practice",
        "stage": 1,
        "description": "The classic shell, editor, data wrangling, Git, debugging, metaprogramming, security, and productivity track.",
        "sourceUrl": "https://missing.csail.mit.edu/2020/",
        "playlistId": "PLyzOVJj3bHQuloKGG59rS43e29ro7I57J",
        "license": "CC BY-NC-SA 4.0",
        "featured": False,
    },
    {
        "id": "harvard-cs50x-2026",
        "title": "CS50x: Introduction to Computer Science",
        "code": "Harvard CS50x",
        "institution": "Harvard University",
        "instructors": ["Prof. David J. Malan"],
        "term": "2026",
        "level": "Introductory",
        "subject": "Programming",
        "stage": 1,
        "description": "A broad introduction to computational thinking, C, Python, SQL, web development, and core CS ideas.",
        "sourceUrl": "https://cs50.harvard.edu/x/2026/",
        "playlistId": "PLhQjrBD2T380hlTqAU8HfvVepCcjCqTg6",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": True,
    },
    {
        "id": "harvard-cs50p-2022",
        "title": "CS50's Introduction to Programming with Python",
        "code": "Harvard CS50P",
        "institution": "Harvard University",
        "instructors": ["Prof. David J. Malan"],
        "term": "2022",
        "level": "Introductory",
        "subject": "Programming",
        "stage": 1,
        "description": "Functions, conditionals, loops, exceptions, libraries, testing, files, regular expressions, and OOP in Python.",
        "sourceUrl": "https://cs50.harvard.edu/python/2022/",
        "playlistId": "PLhQjrBD2T3817j24-GogXmWqO5Q5vYy0V",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": False,
    },
    {
        "id": "harvard-cs50w-2020",
        "title": "Web Programming with Python and JavaScript",
        "code": "Harvard CS50W",
        "institution": "Harvard University",
        "instructors": ["Brian Yu"],
        "term": "2020",
        "level": "Intermediate",
        "subject": "Software Practice",
        "stage": 4,
        "description": "Git, Python, Django, SQL, JavaScript, UI, testing, CI/CD, scalability, and web security.",
        "sourceUrl": "https://cs50.harvard.edu/web/2020/",
        "playlistId": "PLhQjrBD2T380xvFSUmToMMzERZ3qB5Ueu",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": False,
    },
    {
        "id": "harvard-cs50ai-2024",
        "title": "Introduction to Artificial Intelligence with Python",
        "code": "Harvard CS50AI",
        "institution": "Harvard University",
        "instructors": ["Brian Yu"],
        "term": "2024",
        "level": "Intermediate",
        "subject": "AI & Machine Learning",
        "stage": 8,
        "description": "Search, knowledge, uncertainty, optimization, learning, neural networks, and language.",
        "sourceUrl": "https://cs50.harvard.edu/ai/2024/",
        "playlistId": "PLhQjrBD2T381PopUTYtMSstgk-hsTGkVm",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": False,
    },
    {
        "id": "harvard-cs50sql-2024",
        "title": "Introduction to Databases with SQL",
        "code": "Harvard CS50 SQL",
        "institution": "Harvard University",
        "instructors": ["Carter Zenke"],
        "term": "2024",
        "level": "Introductory",
        "subject": "Databases",
        "stage": 4,
        "description": "Relational modeling, querying, normalization, views, indexes, application integration, and scale.",
        "sourceUrl": "https://cs50.harvard.edu/sql/2024/",
        "playlistId": "PLhQjrBD2T382v1MBjNOhPu9SiJ1fsD4C0",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": False,
    },
    {
        "id": "harvard-cs50cyber-2023",
        "title": "Introduction to Cybersecurity",
        "code": "Harvard CS50 Cybersecurity",
        "institution": "Harvard University",
        "instructors": ["Prof. David J. Malan"],
        "term": "2023",
        "level": "Introductory",
        "subject": "Systems & Security",
        "stage": 4,
        "description": "Accounts, data, systems, software, privacy, and practical security tradeoffs.",
        "sourceUrl": "https://cs50.harvard.edu/cybersecurity/2023/",
        "playlistId": "PLhQjrBD2T383Cqo5I1oRrbC1EKRAKGKUE",
        "license": "CC BY-NC-SA 4.0 (CS50 materials)",
        "featured": False,
    },
)


DIRECT_PAGE_COURSES: tuple[dict[str, Any], ...] = (
    {
        "id": "mit-6-s081-fall-2020",
        "title": "Operating System Engineering",
        "code": "MIT 6.S081",
        "institution": "MIT",
        "instructors": ["Prof. Frans Kaashoek", "Prof. Robert Morris"],
        "term": "Fall 2020",
        "level": "Undergraduate",
        "subject": "Systems & Security",
        "stage": 4,
        "description": "xv6, system calls, page tables, traps, concurrency, file systems, virtual memory, networking, and kernels.",
        "sourceUrl": "https://pdos.csail.mit.edu/6.828/2020/schedule.html",
        "license": "Free official course stream; source terms apply",
        "featured": True,
    },
    {
        "id": "mit-6-s087-iap-2024",
        "title": "Foundation Models and Generative AI",
        "code": "MIT 6.S087",
        "institution": "MIT",
        "instructors": ["Rickard Brüel Gabrielsson"],
        "term": "IAP 2024",
        "level": "Undergraduate",
        "subject": "AI & Machine Learning",
        "stage": 8,
        "description": "A non-technical route through representation learning, LLMs, diffusion, self-supervision, and foundation models.",
        "sourceUrl": "https://futureofai.mit.edu/",
        "license": "Free official course stream; source terms apply",
        "featured": False,
    },
    {
        "id": "karpathy-zero-to-hero",
        "title": "Neural Networks: Zero to Hero",
        "code": "Zero to Hero",
        "institution": "Andrej Karpathy",
        "instructors": ["Andrej Karpathy"],
        "term": "Current series",
        "level": "Intermediate",
        "subject": "AI & Machine Learning",
        "stage": 8,
        "description": "Build neural networks, backpropagation, language models, MLPs, WaveNet, and GPT from first principles.",
        "sourceUrl": "https://karpathy.ai/zero-to-hero.html",
        "license": "Free official stream; companion code uses the MIT license",
        "featured": True,
    },
)


def request_bytes(url: str, *, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Content-Type": "application/json" if data is not None else "text/plain",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def request_text(url: str) -> str:
    return request_bytes(url).decode("utf-8", "replace")


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def plain_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", TAG.sub(" ", value))).strip()


def unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def youtube_watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def make_lecture(video_id: str, title: str) -> dict[str, str]:
    if not YOUTUBE_ID.fullmatch(video_id):
        raise ValueError(f"Invalid YouTube video id: {video_id}")
    lecture = {
        "id": video_id,
        "title": plain_text(title) or f"Lecture {video_id}",
        "sourceUrl": youtube_watch_url(video_id),
    }
    if embed_url := OFFICIAL_EMBED_OVERRIDES.get(video_id):
        lecture["embedUrl"] = embed_url
    return lecture


def mit_courses() -> list[dict[str, Any]]:
    query = {
        "query": {
            "bool": {
                "must": [
                    {"match_phrase": {"department_name": "Electrical Engineering and Computer Science"}},
                    {"match_phrase": {"course_feature_tags": "Lecture Videos"}},
                ],
                "filter": [{"term": {"platform": "ocw"}}],
            }
        },
        "size": 100,
    }
    payload = json.loads(request_bytes(MIT_SEARCH_API, data=json.dumps(query).encode("utf-8")))
    return [hit["_source"] for hit in payload["hits"]["hits"]]


def extract_gallery_videos(course_url: str) -> list[dict[str, str]]:
    home = request_text(course_url)
    gallery_urls = unique(
        urllib.parse.urljoin(course_url, html.unescape(href))
        for href in re.findall(r"href=[\"']([^\"']+)[\"']", home, flags=re.IGNORECASE)
        if "video_galleries/" in href
        or re.search(r"/(?:pages/)?(?:lecture-videos|video-lectures)/?$", href)
    )
    lectures: list[dict[str, str]] = []
    seen: set[str] = set()
    for gallery_url in gallery_urls:
        gallery = request_text(gallery_url)
        for match in YOUTUBE_EMBED.finditer(gallery):
            video_id = match.group("id")
            if video_id in seen:
                continue
            nearby = gallery[match.start() : match.start() + 1600]
            title_match = re.search(
                r"class=[\"'][^\"']*video-title[^\"']*[\"'][^>]*>(.*?)</",
                nearby,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if title_match is None:
                continue
            seen.add(video_id)
            lectures.append(make_lecture(video_id, title_match.group(1)))
    return lectures


def mit_subject(course: dict[str, Any]) -> str:
    title = str(course.get("title") or "")
    code = str(course.get("coursenum") or "")
    lowered = title.lower()
    if any(word in lowered for word in ("artificial intelligence", "deep learning", "machine learning", "society of mind", "computational and systems biology")):
        return "AI & Machine Learning"
    if any(word in lowered for word in ("robot", "manufacturing processes")):
        return "Robotics"
    if any(word in lowered for word in ("algorithm", "data structures", "folding")):
        return "Algorithms & Theory"
    if any(word in lowered for word in ("language engineering", "theory of computation")):
        return "Programming Languages"
    if any(word in lowered for word in ("video games", "computer vision", "inverse graphics")):
        return "Graphics, Games & Vision"
    if any(word in lowered for word in ("mathematics", "probab", "stochastic", "nonlinear programming", "computational thinking")):
        return "Mathematics"
    if any(
        word in lowered
        for word in (
            "security",
            "cryptograph",
            "multicore",
            "performance engineering",
            "communication",
        )
    ) or code == "6.004":
        return "Systems & Security"
    if any(word in lowered for word in ("circuits", "signal", "feedback", "electronics")):
        return "Computer Engineering"
    if any(word in lowered for word in ("programming", "structure and interpretation")):
        return "Programming"
    if "copyright" in lowered:
        return "Ethics & Society"
    return "Computer Science"


def subject_stage(subject: str) -> int:
    return {
        "Programming": 1,
        "Software Practice": 1,
        "Mathematics": 2,
        "Algorithms & Theory": 3,
        "Systems & Security": 4,
        "Databases": 4,
        "Computer Engineering": 4,
        "Programming Languages": 6,
        "Ethics & Society": 7,
        "AI & Machine Learning": 8,
        "Graphics, Games & Vision": 9,
        "Robotics": 9,
        "Computer Science": 5,
    }[subject]


def build_mit_ocw_courses() -> list[dict[str, Any]]:
    courses: list[dict[str, Any]] = []
    for source in mit_courses():
        title = str(source.get("title") or "Untitled MIT course")
        if title in MIT_EXCLUDED_TITLES:
            continue
        run = (source.get("runs") or [{}])[0]
        year = int(run.get("year") or 0)
        semester = str(run.get("semester") or "").strip()
        code = str(source.get("coursenum") or "MIT course")
        # 6.004's segmented lecture collection is recovered from its official
        # playlist below because the OCW landing page has no gallery cards.
        if code == "6.004" and year == 2017:
            continue
        course_url = "https://ocw.mit.edu/" + str(run.get("slug") or "").strip("/") + "/"
        lectures = extract_gallery_videos(course_url)
        if not lectures:
            continue
        subject = mit_subject(source)
        term = " ".join(part for part in (semester, str(year) if year else "") if part)
        level_values = run.get("level") or []
        instructors = [str(value) for value in run.get("instructors") or []]
        courses.append(
            {
                "id": slugify(f"mit-{code}-{term}"),
                "title": title,
                "code": f"MIT {code}",
                "institution": "MIT OpenCourseWare",
                "instructors": instructors or ["MIT OpenCourseWare"],
                "term": term or "OpenCourseWare",
                "level": " / ".join(str(value) for value in level_values) or "All levels",
                "subject": subject,
                "stage": subject_stage(subject),
                "description": plain_text(str(source.get("short_description") or "")),
                "sourceUrl": course_url,
                "playlistId": "",
                "license": "CC BY-NC-SA 4.0 (MIT OCW)",
                "featured": code in {"6.006", "6.034", "6.042J", "6.046J", "6.858", "18.404J"},
                "lectures": lectures,
            }
        )
    return courses


def yt_dlp_playlist(playlist_id: str) -> list[dict[str, str]]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--quiet",
        f"https://www.youtube.com/playlist?list={playlist_id}",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "yt-dlp failed").strip()
        raise RuntimeError(f"Could not read YouTube playlist {playlist_id}: {detail}") from exc
    except OSError as exc:
        raise RuntimeError("yt-dlp is required to refresh the video catalog") from exc
    payload = json.loads(completed.stdout)
    lectures: list[dict[str, str]] = []
    for entry in payload.get("entries") or []:
        video_id = str(entry.get("id") or "")
        title = str(entry.get("title") or "")
        if YOUTUBE_ID.fullmatch(video_id) and title:
            lectures.append(make_lecture(video_id, title))
    if not lectures:
        raise RuntimeError(f"YouTube playlist {playlist_id} has no public videos")
    return lectures


def youtube_oembed_title(video_id: str) -> str:
    query = urllib.parse.urlencode({"url": youtube_watch_url(video_id), "format": "json"})
    payload = json.loads(request_bytes(f"https://www.youtube.com/oembed?{query}"))
    return str(payload.get("title") or f"Lecture {video_id}")


def extract_direct_page_videos(course: dict[str, Any]) -> list[dict[str, str]]:
    page = request_text(str(course["sourceUrl"]))
    video_ids = unique(match.group("id") for match in YOUTUBE_EMBED.finditer(page))
    if not video_ids:
        # Some course schedules use ordinary YouTube hrefs with extra query
        # parameters, which the broad embed expression intentionally ignores.
        hrefs = (html.unescape(value) for value in re.findall(r"href=[\"']([^\"']+)[\"']", page))
        for href in hrefs:
            parsed = urllib.parse.urlsplit(href)
            host = (parsed.hostname or "").lower()
            candidate = ""
            if host in {"youtu.be", "www.youtu.be"}:
                candidate = parsed.path.strip("/").split("/")[0]
            elif host.endswith("youtube.com"):
                candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            if YOUTUBE_ID.fullmatch(candidate) and candidate not in video_ids:
                video_ids.append(candidate)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        titles = list(executor.map(youtube_oembed_title, video_ids))
    return [make_lecture(video_id, title) for video_id, title in zip(video_ids, titles, strict=True)]


def attach_playlist(course: dict[str, Any]) -> dict[str, Any]:
    return {**course, "lectures": yt_dlp_playlist(str(course["playlistId"]))}


def attach_direct_page(course: dict[str, Any]) -> dict[str, Any]:
    return {**course, "playlistId": "", "lectures": extract_direct_page_videos(course)}


def deduplicate(courses: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    duplicate_count = 0
    clean_courses: list[dict[str, Any]] = []
    for course in courses:
        lectures = []
        for lecture in course["lectures"]:
            video_id = lecture["id"]
            if video_id in seen:
                duplicate_count += 1
                continue
            seen.add(video_id)
            lectures.append(lecture)
        if not lectures:
            continue
        clean_courses.append({**course, "lectures": lectures, "lectureCount": len(lectures)})
    return clean_courses, duplicate_count


def build_catalog() -> dict[str, Any]:
    courses = build_mit_ocw_courses()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        courses.extend(executor.map(attach_playlist, PLAYLIST_COURSES))
        courses.extend(executor.map(attach_direct_page, DIRECT_PAGE_COURSES))
    courses.sort(
        key=lambda course: (
            not bool(course.get("featured")),
            int(course.get("stage") or 99),
            str(course["title"]).casefold(),
            str(course["term"]).casefold(),
        )
    )
    courses, duplicates = deduplicate(courses)
    subjects = sorted({str(course["subject"]) for course in courses})
    institutions = sorted({str(course["institution"]) for course in courses})
    lecture_count = sum(int(course["lectureCount"]) for course in courses)
    return {
        "version": 1,
        "verifiedAt": date.today().isoformat(),
        "scope": "Public, official or official-course-linked, YouTube-hosted computer science lectures selected for in-app playback.",
        "courses": courses,
        "subjects": subjects,
        "institutions": institutions,
        "stats": {
            "courses": len(courses),
            "lectures": lecture_count,
            "subjects": len(subjects),
            "institutions": len(institutions),
            "duplicatesRemoved": duplicates,
        },
    }


def validate_catalog(catalog: dict[str, Any]) -> None:
    courses = catalog.get("courses")
    if not isinstance(courses, list) or not courses:
        raise ValueError("Catalog has no courses")
    course_ids: set[str] = set()
    video_ids: set[str] = set()
    for course in courses:
        course_id = str(course.get("id") or "")
        if not course_id or course_id in course_ids:
            raise ValueError(f"Duplicate or missing course id: {course_id}")
        course_ids.add(course_id)
        source_url = str(course.get("sourceUrl") or "")
        if urllib.parse.urlsplit(source_url).scheme != "https":
            raise ValueError(f"Course source must use HTTPS: {course_id}")
        lectures = course.get("lectures")
        if not isinstance(lectures, list) or not lectures:
            raise ValueError(f"Course has no lectures: {course_id}")
        for lecture in lectures:
            video_id = str(lecture.get("id") or "")
            if not YOUTUBE_ID.fullmatch(video_id) or video_id in video_ids:
                raise ValueError(f"Invalid or duplicate video id: {video_id}")
            embed_url = str(lecture.get("embedUrl") or "")
            if embed_url:
                parsed_embed = urllib.parse.urlsplit(embed_url)
                if (
                    parsed_embed.scheme != "https"
                    or parsed_embed.hostname != "video.cs50.io"
                    or parsed_embed.path != f"/{video_id}"
                    or parsed_embed.query
                    or parsed_embed.fragment
                ):
                    raise ValueError(f"Invalid official embed override: {video_id}")
            video_ids.add(video_id)
    if len(video_ids) != int(catalog["stats"]["lectures"]):
        raise ValueError("Lecture statistics do not match the catalog")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    try:
        catalog = build_catalog()
        validate_catalog(catalog)
    except (OSError, RuntimeError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"video catalog build failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    print(
        f"Wrote {catalog['stats']['courses']} courses and "
        f"{catalog['stats']['lectures']} unique lectures to {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
