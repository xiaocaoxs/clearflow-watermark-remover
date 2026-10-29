import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.detector import Region, build_tracks, detect_regions


class DetectorTests(unittest.TestCase):
    def test_inset_bottom_username_is_detected(self):
        """平台角标离底边约 30px，不能因为没贴死边缘就被丢掉。"""
        img = np.full((544, 960, 3), (28, 36, 32), np.uint8)
        img[::3, :, 1] = 58
        cv2.putText(img, "clearflow", (96, 508), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (250, 250, 250), 2, cv2.LINE_AA)

        regions = detect_regions(img, white_text=True)

        self.assertTrue(
            any(r.y > 430 and r.x < 400 and r.w > 40 for r in regions),
            [(r.x, r.y, r.w, r.h) for r in regions],
        )

    def test_reappearing_watermark_keeps_separate_time_ranges(self):
        region = Region(8, 138, 74, 44)
        samples = [(t, [region]) for t in (0.0, 0.4, 0.8, 10.0, 10.4, 10.8)]

        tracks = build_tracks(samples)

        self.assertEqual(sorted((tr.t0, tr.t1) for tr in tracks),
                         [(0.0, 0.8), (10.0, 10.8)])

    def test_multiple_boxes_in_one_frame_do_not_count_as_multiple_hits(self):
        samples = [(0.0, [Region(8, 138, 74, 44)] * 3)]

        self.assertEqual(build_tracks(samples, min_hits=3), [])

    def test_merged_duplicate_tracks_count_unique_frames(self):
        samples = [(t, [Region(8, 138, 74, 44)] * 2) for t in (0.0, 0.4, 0.8)]

        tracks = build_tracks(samples)

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].hits, 3)
        self.assertEqual(tracks[0].frame_idx, [0, 1, 2])

    def test_track_stays_on_logo_when_one_hit_is_oversized(self):
        """一次重叠的大框不能把轨迹撑成整块画面，否则时序过滤会丢掉水印。"""
        frames = []
        samples = []
        for i in range(8):
            gray = np.full((200, 200), (i * 37) % 255, np.uint8)
            gray[140:184, 10:84] = 220
            frames.append(gray)
            if i == 3:
                region = Region(0, 40, 100, 150)
            else:
                region = Region(8, 138, 74, 44)
            samples.append((i * 0.4, [region]))

        tracks = build_tracks(samples, min_hits=3, frames_gray=frames)
        logo = [tr for tr in tracks if tr.y1 > 100 and tr.h < 80 and tr.x1 < 40]

        self.assertEqual(len(logo), 1, [(tr.x1, tr.y1, tr.w, tr.h, tr.hits) for tr in tracks])


if __name__ == "__main__":
    unittest.main()
