import json
from pathlib import Path

import pytest


@pytest.fixture
def song_assets(tmp_path: Path) -> tuple[Path, Path]:
    # 読込ロジックを実データに依存せず検証するため、小さなマスターデータと画像を用意する。
    # Pulses=featuring / Futarimiti=複数作曲者 / Saika=Normal 欠落 / 画像は Dream と Futarimiti のみ。
    data = {
        "Story": {
            "Deemo's collection Vol.1A": {
                "Dream": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 4, "Hard": 8},
                    "NOTES": {"Easy": 78, "Normal": 313, "Hard": 485},
                    "TIME": 133,
                    "COMPOSER": ["Rabpit"],
                },
                "Pulses": {
                    "VERSION": "1.0",
                    "LEVEL": {"Easy": 1, "Normal": 6, "Hard": 8},
                    "NOTES": {"Easy": 137, "Normal": 403, "Hard": 569},
                    "TIME": 123,
                    "COMPOSER": ["Sta"],
                    "feat.": ["A"],
                },
            }
        },
        "II": {
            "Etude": {
                "Futarimiti": {
                    "VERSION": "2.3",
                    "LEVEL": {"Easy": 3, "Normal": 6, "Hard": 8},
                    "NOTES": {"Easy": 236, "Normal": 433, "Hard": 783},
                    "TIME": 145,
                    "COMPOSER": ["Morrigan", "Cranky"],
                },
                "Saika": {
                    "VERSION": "2.0",
                    "LEVEL": {"Easy": 2, "Hard": 9},
                    "NOTES": {"Easy": 150, "Hard": 600},
                    "TIME": 120,
                    "COMPOSER": ["X"],
                },
            }
        },
    }
    songs_path = tmp_path / "all_songs.json"
    songs_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "Dream.png").write_bytes(b"\x89PNG\r\n")
    (images_dir / "Futarimiti.png").write_bytes(b"\x89PNG\r\n")
    return songs_path, images_dir
