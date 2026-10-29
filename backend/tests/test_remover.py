import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import remover


class RemoverMaskTests(unittest.TestCase):
    def test_flat_bright_region_is_not_repaired(self):
        frame = np.full((100, 160, 3), 230, np.uint8)
        before = frame.copy()

        remover._repair_frame_region(frame, 35, 30, 125, 70)

        self.assertTrue(np.array_equal(frame, before))

    def test_only_masked_pixels_are_changed(self):
        y, x = np.indices((120, 200))
        texture = np.clip(55 + x * 0.45 + y * 0.25, 0, 180).astype(np.uint8)
        texture = cv2.add(texture, ((x // 12 + y // 12) % 2 * 8).astype(np.uint8))
        frame = cv2.merge((texture, texture, texture))
        cv2.putText(frame, "DEMO", (55, 70), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (245, 245, 245), 2, cv2.LINE_AA)
        before = frame.copy()

        x1, y1, x2, y2 = 45, 42, 145, 82
        margin = remover.REPAIR_MARGIN
        roi = before[y1 - margin:y2 + margin, x1 - margin:x2 + margin]
        inner = np.zeros(roi.shape[:2], np.uint8)
        inner[margin:margin + y2 - y1, margin:margin + x2 - x1] = 255
        mask = remover._extract_shape(roi, inner)

        self.assertGreater(np.count_nonzero(mask), 0)
        self.assertLess(remover._coverage(mask, inner), remover.SHAPE_COVER_MAX)

        remover._repair_frame_region(frame, x1, y1, x2, y2)
        changed = np.any(frame != before, axis=2)
        expected = np.zeros(changed.shape, dtype=bool)
        expected[y1 - margin:y2 + margin, x1 - margin:x2 + margin] = mask > 0

        self.assertGreater(np.count_nonzero(changed), 0)
        self.assertFalse(np.any(changed & ~expected))

    def test_compact_bright_background_is_not_erased(self):
        y, x = np.indices((400, 400))
        gray = (215 + (x % 17) + (y % 9)).astype(np.uint8)
        frame = cv2.merge((gray, gray, gray))
        before = frame.copy()

        remover._repair_frame_region(frame, 30, 140, 150, 200)

        self.assertTrue(np.array_equal(frame, before))

    def test_compact_text_preserves_background_between_letters(self):
        frame = np.full((400, 400, 3), 80, np.uint8)
        for x in (40, 60, 80, 100, 120):
            cv2.rectangle(frame, (x, 150), (x + 3, 175), (245, 245, 245), -1)
        before = frame.copy()

        remover._repair_frame_region(frame, 30, 140, 140, 190)

        self.assertTrue(np.array_equal(frame[145:185, 48:56], before[145:185, 48:56]))
        self.assertLess(float(frame[150:176, 40:44].mean()), 120)

    def test_strong_surrounding_texture_does_not_hide_white_text(self):
        y, x = np.indices((400, 400))
        gray = (((x + y) % 2) * 255).astype(np.uint8)
        frame = cv2.merge((gray, gray, gray))
        frame[140:200, 30:150] = 120
        frame[155:180, 60:63] = 245

        remover._repair_frame_region(frame, 30, 140, 150, 200)

        self.assertLess(float(frame[155:180, 60:63].mean()), 160)

    def test_shape_does_not_escape_detection_bounds(self):
        roi = np.full((70, 100, 3), 60, np.uint8)
        roi[25:45, 30:34] = 245
        inner = np.zeros((70, 100), np.uint8)
        inner[25:45, 30:70] = 255

        shape = remover._extract_shape(roi, inner)

        self.assertGreater(np.count_nonzero(shape), 0)
        self.assertFalse(np.any(shape[inner == 0]))

    def test_compact_badge_interior_is_cleared(self):
        """实心白底角标的内部也要被抹掉，不能只擦掉上面的深色字。"""
        frame = np.full((720, 720, 3), (70, 90, 60), np.uint8)
        cv2.rectangle(frame, (20, 340), (150, 380), (245, 245, 245), -1)
        cv2.putText(frame, "RED", (40, 370), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8, (20, 20, 20), 2, cv2.LINE_AA)
        before = frame.copy()

        remover._repair_frame_region(frame, 16, 334, 156, 386)

        # 整框会向外扩几个像素盖住抗锯齿，框外更远处必须不动
        halo = 8
        outside = before.copy()
        outside[334 - halo:386 + halo, 16 - halo:156 + halo] = frame[
            334 - halo:386 + halo, 16 - halo:156 + halo]
        self.assertTrue(np.array_equal(frame, outside))
        # 白底中心应离开纯白
        self.assertLess(int(frame[360, 80].mean()), 180)


if __name__ == "__main__":
    unittest.main()
