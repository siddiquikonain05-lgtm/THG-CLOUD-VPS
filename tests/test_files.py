import io
import unittest
import zipfile

from app import config, database, file_manager as fm, storage


def make_zip(entries, symlink=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries:
            zf.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


class FileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        storage.ensure_layout()
        database.init()

    def put(self, rel, data):
        (config.DATA_DIR / rel).write_bytes(data)

    def test_default_layout(self):
        names = sorted(p.name for p in config.PROJECTS_DIR.iterdir())
        self.assertIn("my-project", names)
        self.assertIn("another-project", names)
        for f in ("app.py", "holo.txt", "requirements.txt"):
            self.assertTrue((config.PROJECTS_DIR / "my-project" / f).exists())
        self.assertTrue((config.PROJECTS_DIR / "my-project" / "output").is_dir())

    def test_safe_path_blocks_traversal(self):
        for bad in ("../etc/passwd", "projects/../../etc", "/../../etc/shadow"):
            with self.assertRaises(storage.PathError):
                storage.safe_path(bad)
        self.assertEqual(storage.safe_path("projects"), config.PROJECTS_DIR)

    def test_symlink_escape_blocked(self):
        link = config.PROJECTS_DIR / "escape"
        link.symlink_to("/etc")
        try:
            with self.assertRaises(storage.PathError):
                storage.safe_path("projects/escape/passwd")
        finally:
            link.unlink()

    def test_upload_preserves_folders_and_limits(self):
        n = fm.save_stream("projects", "site/css/a.css", io.BytesIO(b"body{}"), 1000)
        self.assertEqual(n, 6)
        self.assertEqual((config.PROJECTS_DIR / "site/css/a.css").read_bytes(), b"body{}")
        with self.assertRaises(fm.FileError):
            fm.save_stream("projects", "../../evil.txt", io.BytesIO(b"x"), 1000)
        with self.assertRaises(fm.FileError):
            fm.save_stream("projects", "big.bin", io.BytesIO(b"x" * 2000), 1000)
        self.assertFalse((config.PROJECTS_DIR / "big.bin").exists())
        self.assertFalse(list(config.PROJECTS_DIR.glob(".big.bin.part")))

    def test_extract_here_and_new_folder(self):
        self.put("projects/my-project/pack.zip", make_zip([("a.txt", "A"), ("sub/b.txt", "B")]))
        r = fm.extract_zip("projects/my-project/pack.zip", "here")
        self.assertEqual(r["files"], 2)
        self.assertEqual((config.PROJECTS_DIR / "my-project/sub/b.txt").read_text(), "B")
        r = fm.extract_zip("projects/my-project/pack.zip", "new_folder")
        self.assertEqual(r["extracted_to"], "projects/my-project/pack")
        r = fm.extract_zip("projects/my-project/pack.zip", "new_folder")
        self.assertEqual(r["extracted_to"], "projects/my-project/pack-2")

    def test_zip_slip_rejected_and_nothing_written(self):
        self.put("projects/evil.zip", make_zip([("ok.txt", "1"), ("../../escaped.txt", "x")]))
        with self.assertRaises(fm.FileError):
            fm.extract_zip("projects/evil.zip", "new_folder")
        self.assertFalse((config.DATA_DIR / "escaped.txt").exists())
        self.assertFalse((config.PROJECTS_DIR / "evil").exists())

    def test_absolute_and_symlink_entries_rejected(self):
        self.put("projects/abs.zip", make_zip([("/tmp/abs-evil.txt", "x")]))
        with self.assertRaises(fm.FileError):
            fm.extract_zip("projects/abs.zip", "new_folder")
        self.put("projects/sym.zip", make_zip([("a.txt", "1")], symlink="link"))
        with self.assertRaises(fm.FileError):
            fm.extract_zip("projects/sym.zip", "new_folder")

    def test_zip_bomb_limit(self):
        old = config.MAX_EXTRACT_MB
        config.MAX_EXTRACT_MB = 1
        try:
            self.put("projects/bomb.zip", make_zip([("big.bin", b"\0" * (3 * 1024 * 1024))]))
            with self.assertRaises(fm.FileError):
                fm.extract_zip("projects/bomb.zip", "new_folder")
            self.assertFalse((config.PROJECTS_DIR / "bomb").exists())
        finally:
            config.MAX_EXTRACT_MB = old

    def test_protected_and_crud(self):
        for p in ("projects", "logs", "system", "database", ""):
            with self.assertRaises(fm.FileError):
                fm.delete(p)
        fm.make_dir("projects/newdir")
        fm.make_file("projects/newdir/x.txt")
        fm.rename("projects/newdir/x.txt", "y.txt")
        with self.assertRaises(fm.FileError):
            fm.rename("projects/newdir/y.txt", "../z.txt")
        listing = fm.list_dir("projects/newdir")
        self.assertEqual([i["name"] for i in listing["items"]], ["y.txt"])
        fm.delete("projects/newdir")
        self.assertFalse((config.PROJECTS_DIR / "newdir").exists())

    def test_download_folder_zip(self):
        fm.make_dir("projects/dl")
        self.put("projects/dl/f.txt", b"hello")
        tmp = fm.zip_dir(config.PROJECTS_DIR / "dl")
        with zipfile.ZipFile(tmp) as zf:
            self.assertIn("dl/f.txt", zf.namelist())


if __name__ == "__main__":
    unittest.main()
