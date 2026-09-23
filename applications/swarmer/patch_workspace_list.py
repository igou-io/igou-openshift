"""Fix upstream 1.4.7's async workspace-list serialization after provider probing."""

from pathlib import Path


source = Path("/app/swarmer/api/v1/workspaces.py")
before = """    accessible = await filter_accessible_workspaces(db, workspaces, identity)
    missing_map = await get_missing_provider_names_bulk([w.id for w in accessible], db)
    output = []
    for workspace in accessible:
        missing = missing_map.get(workspace.id, [])
        item = _to_workspace_out(workspace)
        item.ai_provider_warning = bool(missing)
        item.missing_ai_providers = missing
        output.append(item)
    return output
"""
after = """    accessible = await filter_accessible_workspaces(db, workspaces, identity)
    # Provider probing can expire ORM attributes in this async session.
    output = [_to_workspace_out(workspace) for workspace in accessible]
    missing_map = await get_missing_provider_names_bulk([w.id for w in accessible], db)
    for item in output:
        missing = missing_map.get(item.id, [])
        item.ai_provider_warning = bool(missing)
        item.missing_ai_providers = missing
    return output
"""
text = source.read_text()
if text.count(before) != 1:
    raise SystemExit("Unexpected Swarmer workspace-list source")
source.write_text(text.replace(before, after))
