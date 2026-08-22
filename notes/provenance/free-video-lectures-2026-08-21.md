# Free video lecture catalog — 2026-08-21

## What is in the app

The checked-in video catalog contains **58 complete course tracks** and **1,452
unique lecture videos** across 12 subject areas. Three repeated video IDs found
across overlapping course playlists were removed. The catalog is stored at
`lectures/catalog.json`; no video files, audio files, captions, thumbnails, or
YouTube cookies are stored in this repository.

The app uses YouTube's privacy-enhanced `youtube-nocookie.com` player only after
you choose a lecture. Course search, filters, completion marks, and resume
positions are local. Every course also retains an official course-page link and
every lecture retains its original YouTube link as a playback fallback.
When a publisher's individual YouTube privacy-enhanced embed fails, the catalog
may use that publisher's own frameable player for the same video. CS50x Lecture
0 is the current recorded exception and uses `video.cs50.io`.

## Inclusion rules

A course is included only when all of the following were true during the
2026-08-21 refresh:

1. The course or playlist was published by an institution, instructor, official
   course channel, or linked directly by the official course site.
2. Watching the lecture required no payment or enrollment.
3. Representative videos from the source supported embedded playback in the
   app. Sources whose tested videos rejected embedding were excluded; the
   exact-YouTube fallback remains because publishers can vary the setting per
   video or change it later.
4. It materially supports the CS Library curriculum: programming, mathematics,
   algorithms, systems, security, databases, programming languages, AI/ML,
   graphics, computer engineering, robotics, software practice, or computing
   ethics.
5. Its YouTube video ID did not already appear elsewhere in the catalog.

“Free to stream” is not the same as “freely redistributable.” MIT
OpenCourseWare and the course sites that explicitly publish a Creative Commons
license are labeled accordingly. Other entries say that source terms apply.
The app embeds those official streams; it does not copy or redistribute them.

## Primary sources

- [MIT OpenCourseWare EECS catalog](https://ocw.mit.edu/search/?d=Electrical%20Engineering%20and%20Computer%20Science) — course metadata, official video galleries, instructors, levels, and CC BY-NC-SA 4.0 terms.
- [MIT 6.S081 Operating System Engineering](https://pdos.csail.mit.edu/6.828/2020/schedule.html) — the official schedule links each Fall 2020 recording.
- [MIT 6.824 Distributed Systems](https://pdos.csail.mit.edu/6.824/2020/schedule.html) — official Spring 2020 course and lecture channel.
- [MIT Robotic Manipulation](https://manipulation.csail.mit.edu/Fall2022/schedule.html) and [Underactuated Robotics](https://underactuated.csail.mit.edu/Spring2022/) — official course sites and playlists.
- [MIT 18.S191 Computational Thinking](https://ocw.mit.edu/courses/18-s191-introduction-to-computational-thinking-fall-2020/) — official OCW course and playlist.
- [MIT 6.S191 Introduction to Deep Learning](https://introtodeeplearning.com/) and [MIT 6.S087 Foundation Models and Generative AI](https://futureofai.mit.edu/) — official course sites and linked streams.
- [CMU 15-445 Database Systems](https://15445.courses.cs.cmu.edu/fall2024/) and [CMU 15-721 Advanced Database Systems](https://15721.courses.cs.cmu.edu/spring2024/) — official schedules and CMU Database Group playlists.
- [Harvard CS50](https://cs50.harvard.edu/x/2026/) — the CS50x, Python, Web, AI, SQL, and Cybersecurity course sites and official playlists.
- [The Missing Semester of Your CS Education](https://missing.csail.mit.edu/) — official 2026 and 2020 playlists; site materials are CC BY-NC-SA.
- [Neural Networks: Zero to Hero](https://karpathy.ai/zero-to-hero.html) — Andrej Karpathy's official course page and linked videos.

## Refresh and validation

The refresh script queries MIT's public course index, reads official course
pages, and uses `yt-dlp` in flat-playlist mode to read public playlist metadata.
It never downloads media. To refresh:

```bash
python3 -m pip install yt-dlp
python3 scripts/build_video_catalog.py
python3 -m pytest -q tests/test_library_ui.py
```

The server validates course IDs, HTTPS source URLs, unique 11-character YouTube
IDs, nonempty course tracks, and the recorded totals before exposing
`/api/lectures`. Source publishers can still remove a video, disable embedding,
apply a regional restriction, or revise a playlist later. In that case, use the
course-site or YouTube fallback in the player and refresh the catalog.
