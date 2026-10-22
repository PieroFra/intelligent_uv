# pylint: disable=invalid-name
"""
Intelligent UV Mapping — NON-DESTRUCTIVE PREVIEW

Lets a run be looked at before it is kept.

Unwrapping overwrites two things that are expensive to recreate by hand: the
seams on the mesh and whatever was in the target UV layer. Blender's undo is
the usual safety net and it is not one here — the run enters and leaves Edit
Mode several times, calls operators that push their own undo steps, and on the
external path shells out to another process entirely. Pressing Ctrl+Z after that
lands somewhere unpredictable in the middle of the pipeline rather than before
it.

So the state is captured explicitly, before anything is written, and restored
exactly on request. Seams go into a boolean edge attribute rather than a Python
list because the list would not survive saving the file, closing Blender and
coming back to a preview still waiting to be judged.

The backup lives on the mesh and is removed the moment the preview is accepted
or discarded, so a file never carries a stale one around.
"""


from .utils import loop_uv, set_loop_uv

SEAM_BACKUP = "iuv_seam_backup"
UV_BACKUP_SUFFIX = "_preview_backup"


def _edge_count(mesh):
    return len(getattr(mesh, "edges", []))


def save_seams(mesh):
    """
    Copies the current seams into a boolean edge attribute.

    Returns (ok, message).
    """
    edges = getattr(mesh, "edges", None)
    attributes = getattr(mesh, "attributes", None)

    if edges is None or attributes is None:
        return False, "This mesh does not expose edges or attributes."

    count = len(edges)
    if count == 0:
        return False, "The mesh has no edges."

    existing = attributes.get(SEAM_BACKUP)
    if existing is not None:
        try:
            attributes.remove(existing)
        except Exception as exc:
            return False, f"Could not clear the previous seam backup: {exc}"

    try:
        attribute = attributes.new(SEAM_BACKUP, 'BOOLEAN', 'EDGE')
    except Exception as exc:
        return False, f"Could not create the seam backup: {exc}"

    try:
        flags = [False] * count
        edges.foreach_get("use_seam", flags)
        attribute.data.foreach_set("value", flags)
    except Exception:
        # A: foreach_get/set on these is not available on every build.
        try:
            for i in range(count):
                attribute.data[i].value = bool(edges[i].use_seam)
        except Exception as exc:
            return False, f"Could not record the seams: {exc}"

    return True, f"Recorded {sum(1 for e in edges if e.use_seam)} existing seams."


def restore_seams(mesh):
    """Puts the recorded seams back. Returns (ok, message)."""
    edges = getattr(mesh, "edges", None)
    attributes = getattr(mesh, "attributes", None)

    if edges is None or attributes is None:
        return False, "This mesh does not expose edges or attributes."

    attribute = attributes.get(SEAM_BACKUP)
    if attribute is None:
        return False, "No seam backup on this mesh."

    count = min(len(edges), len(attribute.data))

    try:
        flags = [False] * count
        attribute.data.foreach_get("value", flags)
        edges.foreach_set("use_seam", flags)
    except Exception:
        # A: same fallback as above.
        try:
            for i in range(count):
                edges[i].use_seam = bool(attribute.data[i].value)
        except Exception as exc:
            return False, f"Could not restore the seams: {exc}"

    return True, f"Restored {sum(1 for f in flags if f)} seams."


def save_uv_layer(mesh, name):
    """
    Copies the target UV layer aside, if it exists.

    Returns (ok, message). A missing layer is not a failure: it means the run
    is creating it, and discarding should delete it rather than restore
    anything.
    """
    uv_layers = getattr(mesh, "uv_layers", None)
    if uv_layers is None:
        return False, "This mesh has no UV layers."

    source = uv_layers.get(name)
    if source is None:
        return True, "No existing UV layer to preserve."

    backup_name = f"{name}{UV_BACKUP_SUFFIX}"

    existing = uv_layers.get(backup_name)
    if existing is not None:
        uv_layers.remove(existing)

    try:
        backup = uv_layers.new(name=backup_name)
    except Exception as exc:
        return False, f"Could not create the UV backup: {exc}"

    if backup is None:
        return False, "Could not create the UV backup."

    count = min(len(source.data), len(backup.data))
    for i in range(count):
        uv = loop_uv(source, i)
        if uv is not None:
            set_loop_uv(backup, i, uv[0], uv[1])

    return True, f"Preserved the previous '{name}'."


def restore_uv_layer(mesh, name):
    """Puts the preserved UV layer back, or removes the one the run created."""
    uv_layers = getattr(mesh, "uv_layers", None)
    if uv_layers is None:
        return False, "This mesh has no UV layers."

    backup_name = f"{name}{UV_BACKUP_SUFFIX}"
    backup = uv_layers.get(backup_name)
    target = uv_layers.get(name)

    if backup is None:
        # Nothing was preserved, so the layer did not exist before the run.
        if target is not None:
            uv_layers.remove(target)
            return True, f"Removed '{name}', which the preview created."
        return False, "Nothing to restore."

    if target is None:
        return False, f"'{name}' is gone; cannot restore into it."

    count = min(len(backup.data), len(target.data))
    for i in range(count):
        uv = loop_uv(backup, i)
        if uv is not None:
            set_loop_uv(target, i, uv[0], uv[1])

    uv_layers.remove(backup)
    return True, f"Restored the previous '{name}'."


def clear_backups(mesh, name):
    """Drops both backups. Called when a preview is accepted."""
    removed = []

    attributes = getattr(mesh, "attributes", None)
    if attributes is not None:
        attribute = attributes.get(SEAM_BACKUP)
        if attribute is not None:
            try:
                attributes.remove(attribute)
                removed.append("seams")
            except Exception:
                # B: a leftover attribute is harmless but should be visible.
                print("[IUV_PREVIEW] Could not remove the seam backup.")

    uv_layers = getattr(mesh, "uv_layers", None)
    if uv_layers is not None:
        backup = uv_layers.get(f"{name}{UV_BACKUP_SUFFIX}")
        if backup is not None:
            try:
                uv_layers.remove(backup)
                removed.append("UVs")
            except Exception:
                print("[IUV_PREVIEW] Could not remove the UV backup.")

    return removed


def has_pending(mesh):
    """True when a preview on this mesh is still waiting to be judged."""
    attributes = getattr(mesh, "attributes", None)
    return attributes is not None and attributes.get(SEAM_BACKUP) is not None


def capture(mesh, uv_layer_name):
    """
    Records everything a run is about to overwrite.

    Returns (ok, messages). Seams are captured first: if that fails there is
    no safe preview, and creating the UV backup alone would leave the mesh
    half-protected in a way that looks fine until a discard is attempted.
    """
    messages = []

    ok, message = save_seams(mesh)
    messages.append(message)
    if not ok:
        return False, messages

    ok, message = save_uv_layer(mesh, uv_layer_name)
    messages.append(message)
    if not ok:
        # Roll the seam backup back rather than leaving it dangling.
        clear_backups(mesh, uv_layer_name)
        return False, messages

    return True, messages


def revert(mesh, uv_layer_name):
    """Undoes a previewed run completely. Returns (ok, messages)."""
    messages = []

    ok_uv, message = restore_uv_layer(mesh, uv_layer_name)
    messages.append(message)

    ok_seams, message = restore_seams(mesh)
    messages.append(message)

    clear_backups(mesh, uv_layer_name)

    if hasattr(mesh, "update"):
        try:
            mesh.update()
        except Exception:
            # A: mesh.update() is not required on every Blender version.
            pass

    return (ok_uv or ok_seams), messages
