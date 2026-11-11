# CINE-Interfaces

The CINE drone runs as two programs in two repositories. CINE-Sensing runs on the
Raspberry Pi on the drone and handles the camera, IMU, detection and visual-inertial
odometry. CINE runs on the ground PC and handles depth, planning and cinematography.
They talk over Wi-Fi through ROS 2 topics, and nothing stops one side from renaming a
topic the other side still listens on.

This repository holds the list of those topics, `contract.json`, and a checker that
compares each repository against it. Each consuming repository runs the checker as an
ordinary pytest test, so a rename that breaks the other side fails CI on the side that
made it.

## The contract

`cine_interfaces/cine_interfaces/contract.json` lists every stream that crosses the
link. A stream has a key such as `position_pose`, a message type, a direction
(`pi_to_ground` or `ground_to_pi`), and its publishers and subscribers. Each endpoint
names its repository, its node, its topic, and where that topic name comes from in the
code (its *source*). The checker reads the name from that source and compares it with
the contract.

There are four kinds of source:

| Kind | Where the name is read from | Fields |
| --- | --- | --- |
| `code` | a `create_publisher` or `create_subscription` call with a string literal topic | `file` |
| `config` | a key in a JSON config file, plus the same key in any profile under `profiles/*/` | `file`, `key` (list of keys) |
| `launch` | a parameter in a dict literal passed to `Node(executable=...)` in a launch file | `file`, `executable`, `parameter` |
| `unchecked` | nowhere: the name is computed, lives in C++, or belongs to neither repository | `reason` |

An unchecked endpoint is reported as information on every run, so the gap stays visible.

### Accepted mismatches

Some streams do not line up today: the two sides use different topic names, or one side
has no publisher yet. Those streams carry `"accepted_mismatch": true`. The checker
reports them as information instead of an error, so CI passes while the mismatch is
recorded where everyone can see it. Fixing one means making the names agree in both
repositories and then setting the flag back to `false`, which turns any regression into
an error.

## Changing a topic that crosses the link

Edit `contract.json` first, in this repository. Then change the code in CINE-Sensing
and CINE to match, and move each repository's pinned commit of CINE-Interfaces forward.
A rename made only in one repository fails that repository's drift test.

## Install

For plain Python, which is what the drift tests use:

```bash
pip install -e cine_interfaces
```

As a ROS 2 package, clone this repository into a colcon workspace's `src/` folder and
run `colcon build --packages-select cine_interfaces`.

## Commands

Check a repository checkout without running anything:

```bash
python3 -m cine_interfaces.check CINE-Sensing ../CINE-Sensing
python3 -m cine_interfaces.check CINE ../CINE
```

Check a running ROS 2 graph (needs a sourced ROS 2 setup, so `ros2` is on the path):

```bash
python3 -m cine_interfaces.check --live
python3 -m cine_interfaces.check --live --strict   # accepted mismatches become errors
```

Both commands print one line per finding and a count. `--json` prints a single JSON
report instead, with `ok`, `errors` and `findings`. `--contract PATH` checks against a
contract file other than the packaged one.

| Exit code | Meaning |
| --- | --- |
| 0 | no errors (information lines may still appear) |
| 1 | at least one error finding |
| 2 | the check could not run: bad arguments, unreadable contract, or `ros2` missing |

## Development

```bash
pytest                              # unit tests
python3 tools/format.py --check     # whitespace convention, then ruff format
ruff check .
pre-commit run --all-files
```

## License

GPL-3.0-only. See `LICENSE`.
