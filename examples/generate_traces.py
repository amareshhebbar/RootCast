import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from scenarios import SCENARIOS, TickClock


def generate(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for name, module in SCENARIOS.items():
        path = os.path.join(out_dir, name + ".rootcast.json")
        module.run(path, clock=TickClock())
        paths.append(path)
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(HERE, "traces"))
    args = parser.parse_args(argv)
    for path in generate(args.out):
        print("wrote " + os.path.relpath(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
