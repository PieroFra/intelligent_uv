# pylint: disable=invalid-name
"""
Intelligent UV Mapping — RIZOMUV LINK BRIDGE

Drives RizomUV through `RizomUVLink`, the official Python API published by
Rizom-Lab under the MIT licence. The module talks to a running RizomUV instance
over a local ZeroMQ socket and exposes the application's real commands —
`Load`, `Unfold`, `Optimize`, `Pack`, `Save`, `Quit` — instead of writing a Lua
script and hoping it parses.

Why this replaced the script path:
the `-cfi <script>` flag does not run a batch and exit. It attaches a *remote
file* that RizomUV watches for changes, so a script ending in `ZomQuit()` never
completes the way a batch would: the process sits waiting and the run times out.
The headless flag is `-id <port>`, which is what `RunRizomUV` uses.

Availability:
the API ships as a `win_amd64` wheel, so this path exists on Windows only, and
only when the module is importable. Everywhere else the add-on falls back to the
manual Export/Import round trip, which needs no external library.

The work is split into steps driven by the modal timer, and each step runs on
a worker thread: the link API is synchronous, so a dense unfold or pack would
otherwise park Blender inside a socket call that a crashed RizomUV never
answers. While the step runs, the modal loop watches the RizomUV process
itself (found via the link port) and can abort, time out, or report the
crash instead of freezing.
"""

import glob
import os
import subprocess
import sys
import threading
import time


from .rizomuv_bridge import RizomUVBridge

# The API is imported lazily: it is absent on macOS and Linux, and absent on
# Windows unless RizomUV or a bridge that bundles the wheel is installed.
_LINK_MODULE = None
_LINK_IMPORT_ERROR = None
_PATH_PROBED = False


def ensure_link_on_path(exe_path=None):
    """
    Makes the RizomUVLink module importable when it ships with RizomUV.

    RizomUV 2025 bundles the API in `<install dir>/RizomUVLink` (with .pyd
    builds per Python version) but nothing puts that folder on Blender's
    sys.path, so a plain `import RizomUVLink` fails even on machines that
    have everything needed. The folder next to the configured executable is
    tried first, then the standard install root.
    """
    global _LINK_IMPORT_ERROR, _PATH_PROBED

    if _PATH_PROBED:
        return
    _PATH_PROBED = True

    candidates = []

    if exe_path:
        candidates.append(
            os.path.join(os.path.dirname(str(exe_path)), "RizomUVLink")
        )

    candidates.extend(
        glob.glob(r"C:\Program Files\Rizom Lab\*\RizomUVLink")
    )

    added = False
    for candidate in candidates:
        if os.path.isdir(candidate) and candidate not in sys.path:
            sys.path.append(candidate)
            added = True

    if added:
        # A previous import attempt may have failed before the path was added;
        # clear the cached error so link_module() tries again.
        _LINK_IMPORT_ERROR = None


def link_module():
    """Returns the RizomUVLink module, or None when it is unavailable."""
    global _LINK_MODULE, _LINK_IMPORT_ERROR

    if _LINK_MODULE is not None or _LINK_IMPORT_ERROR is not None:
        return _LINK_MODULE

    try:
        import RizomUVLink  # noqa: PLC0415  (deliberately lazy)
        _LINK_MODULE = RizomUVLink
    except Exception as exc:
        _LINK_IMPORT_ERROR = exc
        _LINK_MODULE = None

    return _LINK_MODULE


def is_available():
    """True when the live link can be used on this machine."""
    return link_module() is not None


# ----------------------------------------------------------------------
# Process watching
#
# The link API returns a port, not a PID. Knowing *which* rizomuv.exe we
# launched lets the modal loop tell "RizomUV is busy" apart from "RizomUV
# is gone" — without it, a crash mid-Unfold leaves Blender parked inside a
# blocking socket call that will never be answered.
# ----------------------------------------------------------------------

_STILL_ACTIVE = 259


def _find_pid_for_port(port, attempts=5, delay=0.4):
    """PID of the process listening on the link port, Windows only."""
    if os.name != "nt" or not port:
        return None

    suffix = f":{int(port)}"
    for _ in range(attempts):
        try:
            out = subprocess.check_output(
                ["netstat", "-ano"], text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return None

        for line in out.splitlines():
            parts = line.split()
            if (len(parts) >= 5 and parts[0].startswith("TCP")
                    and parts[1].endswith(suffix) and parts[3] == "LISTENING"):
                try:
                    return int(parts[4])
                except ValueError:
                    continue

        time.sleep(delay)

    return None


def _pid_alive(pid):
    """True while the watched process exists and has not exited."""
    if not pid:
        # Unknown PID: cannot prove death, assume alive.
        return True

    if os.name == "nt":
        import ctypes  # noqa: PLC0415  (Windows-only, deliberately lazy)

        kernel32 = ctypes.windll.kernel32
        # PROCESS_QUERY_LIMITED_INFORMATION
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(0)
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _kill_pid(pid):
    """Hard-kills the watched process. Used only when it is hung or the
    user aborted: a graceful Quit needs a responsive app on the other end."""
    if not pid:
        return

    if os.name == "nt":
        import ctypes  # noqa: PLC0415

        kernel32 = ctypes.windll.kernel32
        # PROCESS_TERMINATE
        handle = kernel32.OpenProcess(0x0001, False, int(pid))
        if handle:
            try:
                kernel32.TerminateProcess(handle, 1)
            finally:
                kernel32.CloseHandle(handle)
        return

    try:
        os.kill(int(pid), 15)
    except OSError:
        # B: the process is already gone, which is the outcome wanted.
        pass


def unavailable_reason():
    """Human-readable explanation for why the live link cannot be used."""
    if is_available():
        return ""

    return (
        "RizomUVLink is not importable. It ships as a Windows-only wheel with "
        "RizomUV 2025 and later. On macOS and Linux, or without it installed, "
        "use Export FBX / Import FBX instead."
        + (f" ({_LINK_IMPORT_ERROR})" if _LINK_IMPORT_ERROR else "")
    )


class RizomUVLinkBridge:
    """
    Step-driven bridge over the RizomUV live link.

    The caller advances one step per modal tick:

        prepare()    export the FBX, build the step list
        start()      launch or attach to RizomUV, record its PID
        step_begin() start the next command on a worker thread
        step_poll()  non-blocking check: running / done / error
        step()       synchronous begin+wait, for background and tests
        finalize()   import the result back onto the object
        cleanup()    close the link and remove temp files
    """

    # RizomUV is asked to keep the shells it was given rather than re-cutting
    # them: the seams were already planned here, and the pre-unwrap turned them
    # into island borders that survive the FBX roundtrip.
    STEP_LABELS = {
        "load": "loading the mesh",
        "setup": "configuring margins and resolution",
        "unfold": "unfolding islands",
        "optimize": "reducing stretch",
        "pack": "packing islands",
        "save": "saving the result",
    }

    @classmethod
    def prepare(cls, obj, settings, is_seam, margin_result, report=None):
        """
        Exports the FBX and builds the command sequence.

        Reuses the same export the script bridge and the manual Export button
        use, so all three produce an identical file.
        """
        if not is_available():
            raise RuntimeError(unavailable_reason())

        # Seam marking, native pre-unwrap and FBX export are shared with the
        # script bridge; only the external half differs.
        ctx = RizomUVBridge.prepare(
            obj, settings, is_seam, margin_result, report=report
        )

        # The Lua script the shared prepare wrote is not used on this path.
        ctx["lua_path"] = ctx.get("lua_path")
        ctx["steps"] = cls._build_steps(settings, margin_result)
        ctx["step_index"] = 0
        ctx["link"] = None
        ctx["mode"] = "link"

        return ctx

    @classmethod
    def _build_steps(cls, settings, margin_result):
        """
        The command sequence, as (name, method, params) tuples.

        Pack margins, map resolution and island scaling are written to the
        document through `Set` on the `Lib.Mesh.RootGroup.Properties.Pack`
        table (the "setup" step, right after Load): RizomUV packs with pixel
        units by default (UsePixelUnit=true), so the UV-unit MarginSize we
        used to pass to Pack was silently ignored and every pack ran with
        whatever padding the last session had — wrong at any texture
        resolution that was not the stored one.

        Verified empirically against RizomUV 2025.0.117:
        - Get/Set/ItemNames take bare dotted paths, e.g.
          "Lib.Mesh.RootGroup.Properties.Pack.PaddingSizePx".
        - With UsePixelUnit=true the active values are PaddingSizePx /
          MarginSizePx at MapResolution; the UV-unit twins are derived.
        - Scaling.Mode=0 (OFF) keeps the island sizes our texel-density
          normalization produced; the default 2 re-averages them.
        - Pack rejects unknown parameters; Unfold rejects ProcessNonFlats
          and ProcessSelection.
        """
        margin_px = max(1, int(round(float(margin_result.margin_px))))
        tex_res = max(64, int(margin_result.texture_resolution))

        pack_root = "Lib.Mesh.RootGroup.Properties.Pack"
        setup = [
            (f"{pack_root}.MapResolution", tex_res),
            (f"{pack_root}.UsePixelUnit", True),
            (f"{pack_root}.PaddingSizePx", margin_px),
            (f"{pack_root}.MarginSizePx", margin_px),
            (f"{pack_root}.Scaling.Mode", 0),
        ]

        steps = [
            ("load", "Load", None),          # params built at run time
            ("setup", "Set", setup),         # pack properties on the document
            ("unfold", "Unfold", {
                "WorkingSet": "Visible",
                "PrimType": "Island",
                "Mix": 1,
            }),
            ("optimize", "Optimize", {
                "WorkingSet": "Visible",
                "PrimType": "Island",
            }),
            ("pack", "Pack", {
                "WorkingSet": "Visible",
                "RootGroup": "RootGroup",
                "Translate": True,
                "Rotate": {"Mode": 4},
            }),
            ("save", "Save", None),          # params built at run time
        ]

        if not bool(getattr(settings, "link_optimize", True)):
            steps = [s for s in steps if s[0] != "optimize"]

        return steps

    @classmethod
    def start(cls, ctx, settings):
        """Launches RizomUV (or attaches to one) and opens the link."""
        module = link_module()
        if module is None:
            raise RuntimeError(unavailable_reason())

        rz_path = str(getattr(settings, "rizomuv_path", "") or "").strip()

        try:
            link = module.CRizomUVLink()
        except Exception as exc:
            raise RuntimeError(f"Unable to create the RizomUV link: {exc}") from exc

        # `RunRizomUV` picks a free port, starts the process with `-id <port>`
        # and waits until it answers. That is the real headless invocation;
        # `-cfi` attaches a watched remote file and never terminates on its own.
        #
        # The port is chosen here (not left to the module) for one reason:
        # when the startup wait times out, RunRizomUV leaves the half-started
        # instance running, and a lingering instance makes every later launch
        # time out too (observed on 2025.0.117). Knowing the port lets us
        # find that orphan by netstat and kill it before raising.
        port = None
        for candidate in range(49152, 65534):
            try:
                if not link.TCPPortIsOpen(candidate):
                    port = candidate
                    break
            except Exception:
                break

        try:
            if port is not None:
                link.RunRizomUV(
                    rz_path if os.path.isfile(rz_path) else None, port=port)
            else:
                port = link.RunRizomUV(
                    rz_path if os.path.isfile(rz_path) else None)
        except Exception as exc:
            orphan = _find_pid_for_port(port) if port else None
            if orphan:
                _kill_pid(orphan)
            raise RuntimeError(
                f"Unable to start RizomUV: {exc}. Another RizomUV instance "
                "may already be running — close it and try again."
            ) from exc

        ctx["link"] = link
        ctx["port"] = port
        ctx["pid"] = _find_pid_for_port(port)
        ctx["job"] = None
        ctx["keep_open"] = bool(getattr(settings, "link_keep_open", False))

        try:
            ctx["step_timeout"] = float(max(30, int(
                getattr(settings, "rizomuv_timeout", 300) or 300
            )))
        except Exception:
            ctx["step_timeout"] = 300.0

        try:
            ctx["version"] = str(link.RizomUVVersion())
        except Exception:
            # A: the version call is informational; a failure must not abort.
            ctx["version"] = "unknown"

        return link

    @classmethod
    def step_begin(cls, ctx):
        """
        Starts the next command on a worker thread and returns its label,
        or None when the sequence is complete.

        The link API is synchronous; running it on a worker keeps the modal
        timer alive, so the overall timeout, the ESC abort and the process
        watch keep working while RizomUV unfolds or packs. The worker only
        talks to the socket — it never touches bpy.
        """
        link = ctx.get("link")
        if link is None:
            raise RuntimeError("The RizomUV link is not open.")

        steps = ctx.get("steps") or []
        index = ctx.get("step_index", 0)

        if index >= len(steps):
            return None

        if ctx.get("job") is not None:
            raise RuntimeError("A RizomUV command is already running.")

        name, method_name, params = steps[index]

        # Load and Save need paths, which live in the context. Flat dotted
        # keys, the form the official RizomUVLink examples use (verified
        # against 2025.0.117).
        if name == "load":
            params = {
                # Forward slashes: Windows backslashes are an escape
                # hazard once the path crosses into the API.
                "File.Path": str(ctx["export_path"]).replace("\\", "/"),
                "File.XYZUVW": True,
                "File.UVWProps": True,
                "File.ImportGroups": True,
            }
        elif name == "save":
            params = {
                "File.Path": str(ctx["import_path"]).replace("\\", "/"),
                "File.UVWProps": True,
            }

        method = getattr(link, method_name, None)
        if method is None:
            raise RuntimeError(
                f"The RizomUV API has no '{method_name}' command; "
                "the installed version may be older than 2025."
            )

        label = cls.STEP_LABELS.get(name, name)
        job = {
            "label": label,
            "started": time.monotonic(),
            "done": False,
            "exc": None,
            "thread": None,
        }

        def _run():
            try:
                if name == "setup":
                    # One Set per (path, value) pair; a single failure aborts
                    # the step so the pack does not run with half-applied
                    # settings.
                    for path, value in params or []:
                        method({"Path": path, "Value": value})
                    ret = None
                else:
                    ret = method(params or {})
                # Command payloads carry soft failures (e.g. Unfold's
                # BijectionFailedIslandIDs) that never raise; keep them so
                # finalize can warn about what RizomUV could not do.
                ctx.setdefault("results", {})[name] = ret
            except Exception as exc:  # socket errors, API rejections
                job["exc"] = RuntimeError(
                    f"RizomUV failed while {label}: {exc}"
                )
            finally:
                job["done"] = True

        job["thread"] = threading.Thread(target=_run, daemon=True)
        job["thread"].start()
        ctx["job"] = job

        return label

    @classmethod
    def step_poll(cls, ctx):
        """
        Checks the running command without blocking.

        Returns (status, label, error) with status in
        {"running", "done", "error"}. A dead or hung RizomUV is reported as
        "error" instead of freezing the caller on a socket that will never
        answer.
        """
        job = ctx.get("job")
        if job is None:
            raise RuntimeError("No RizomUV command is running.")

        label = job["label"]

        if not job["done"]:
            pid = ctx.get("pid")
            if pid and not _pid_alive(pid):
                job["exc"] = RuntimeError(
                    f"RizomUV closed unexpectedly while {label}. The mesh "
                    "may be too heavy for it; try a decimated copy."
                )
                job["done"] = True
            elif (time.monotonic() - job["started"]
                    > ctx.get("step_timeout", 300.0)):
                _kill_pid(pid)
                job["exc"] = RuntimeError(
                    f"RizomUV did not answer within "
                    f"{int(ctx.get('step_timeout', 300))}s while {label} "
                    "and was closed."
                )
                job["done"] = True
            else:
                return "running", label, None

        thread = job.get("thread")
        if thread is not None:
            thread.join(timeout=1.0)

        ctx["job"] = None

        if job["exc"] is not None:
            return "error", label, job["exc"]

        ctx["step_index"] = ctx.get("step_index", 0) + 1
        return "done", label, None

    @classmethod
    def step_elapsed(cls, ctx):
        """Seconds since the running command started, for progress text."""
        job = ctx.get("job")
        if job is None:
            return 0.0
        return time.monotonic() - job["started"]

    @classmethod
    def step(cls, ctx):
        """
        Synchronous one-shot advance, kept for background and test use:
        begins the next command and waits for it. Returns (finished, message)
        and raises on failure, so the caller can degrade to the native
        result, as with the script path.
        """
        label = cls.step_begin(ctx)
        if label is None:
            return True, "RizomUV sequence complete."

        while True:
            status, _label, exc = cls.step_poll(ctx)
            if status == "running":
                time.sleep(0.05)
                continue
            if status == "error":
                raise exc
            break

        finished = ctx.get("step_index", 0) >= len(ctx.get("steps") or [])
        return finished, label

    @classmethod
    def progress_fraction(cls, ctx):
        """How far through the command sequence, from 0 to 1."""
        steps = ctx.get("steps") or []
        if not steps:
            return 1.0
        return min(1.0, ctx.get("step_index", 0) / float(len(steps)))

    @classmethod
    def finalize(cls, obj, settings, ctx):
        """Imports the saved FBX back onto the object."""
        import_path = ctx.get("import_path")

        if not import_path or not os.path.isfile(import_path):
            raise RuntimeError(
                "RizomUV did not write the output FBX. The Save command may "
                "have failed silently."
            )

        margin_result = ctx["margin_result"]

        uv_name, copied, unmatched, total, fit_info = \
            RizomUVBridge.import_uvs_from_fbx(
                obj, settings, import_path,
                margin_uv=float(getattr(margin_result, "margin_uv", 0.0)
                                or 0.0),
            )

        # Unfold reports islands it could not flatten through the command's
        # return payload, not as an error — surface them to the user.
        unfold_ret = (ctx.get("results") or {}).get("unfold")
        failed_islands = []
        if isinstance(unfold_ret, dict):
            failed_islands = list(
                unfold_ret.get("BijectionFailedIslandIDs") or [])
        if failed_islands:
            print(f"[IUV_RIZOMLINK] RizomUV could not unfold "
                  f"{len(failed_islands)} islands (non-manifold or "
                  "degenerate geometry); those islands kept their "
                  "pre-computed UVs.")

        return {
            "uv_layer": uv_name,
            "copied_loops": copied,
            "unmatched_faces": unmatched,
            "total_faces": total,
            "margin_px": margin_result.margin_px,
            "texture_resolution": margin_result.texture_resolution,
            "version": ctx.get("version", "unknown"),
            "fit_to_tile": bool(fit_info.get("fitted")),
            "fit_scale": float(fit_info.get("scale", 1.0)),
            "unfold_failed_islands": len(failed_islands),
        }

    @classmethod
    def terminate(cls, ctx, force=False):
        """
        Closes RizomUV. Safe to call more than once.

        force=True is for aborts and timeouts: a graceful Quit would block
        on an app that is busy or hung, so the process is killed instead —
        unless the user asked to keep RizomUV open, in which case we just
        drop our end of the link.
        """
        link = ctx.get("link")
        pid = ctx.get("pid")

        if force:
            if not ctx.get("keep_open"):
                _kill_pid(pid)
            ctx["link"] = None
            return

        if link is None:
            return

        if ctx.get("keep_open"):
            # Leave the app running so the result can be inspected.
            ctx["link"] = None
            return

        if pid and not _pid_alive(pid):
            # Already gone (crash, or the user closed it): nothing to quit.
            ctx["link"] = None
            return

        try:
            # Empty params, matching the official RizomUVLink examples.
            link.Quit({})
        except Exception as exc:
            # B: RizomUV may already be gone; say so rather than hiding it.
            print(f"[IUV_RIZOMLINK] Quit failed: {exc}")

        ctx["link"] = None

        # Quit is asynchronous: a large scene takes seconds to tear down.
        # Wait briefly so a follow-up run does not meet a half-closed
        # instance, but never park the UI over it — it exits on its own.
        if pid:
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and _pid_alive(pid):
                time.sleep(0.25)
            if _pid_alive(pid):
                print("[IUV_RIZOMLINK] RizomUV is still shutting down.")

    @classmethod
    def cleanup(cls, ctx, failed=False):
        """Closes the link and hands the temp files to the shared cleanup."""
        cls.terminate(ctx)
        RizomUVBridge.cleanup(ctx, failed=failed)
