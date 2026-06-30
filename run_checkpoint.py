import io, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force UTF-8 everywhere
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

outfile = open("checkpoint_result.txt", "w",
               encoding="utf-8", errors="replace",
               buffering=1)

class Tee(io.TextIOBase):
    def write(self, data):
        try:
            sys.stdout.buffer.write(
                data.encode("utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        except Exception:
            pass
        try:
            outfile.write(data)
            outfile.flush()
        except Exception:
            pass
        return len(data)
    def flush(self):
        try: outfile.flush()
        except: pass

tee = Tee()
sys.stdout = tee
sys.stderr = tee

from tests.checkpoint_phase4 import main
main()
outfile.close()
