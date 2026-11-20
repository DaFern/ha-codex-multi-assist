"""Approved experimental constructor interception for enrolled ESPHome entries.

This is a class-wide runtime patch, not a supported HA extension point. Only
enrolled config entries receive instance hooks. Installation is synchronous:
replacement instances cannot be returned to ESPHome's subscription setup until
the owner has installed their protection. No intent or service handler is patched.
"""

_GUARDS = {}


class _ConstructorGuard:
    def __init__(self, native):
        self.native = native
        self.previous = native.__dict__.get("__init__")
        self.original = native.__init__
        self.owners = {}

        def construct(satellite, *args, **kwargs):
            self.original(satellite, *args, **kwargs)
            entry = args[0] if args else kwargs.get("entry")
            entry_id = getattr(entry, "entry_id", None)
            for (hass_id, enrolled_entry_id), (owner, entity_id) in tuple(self.owners.items()):
                if (
                    enrolled_entry_id == entry_id
                    and id(owner.hass) == hass_id
                    and owner.hass.config_entries.async_get_entry(entry_id) is entry
                ):
                    # Do not swallow errors: failing construction is safer than
                    # returning an enrolled, unguarded object to audio setup.
                    owner.attach_instance(entity_id, satellite, constructed=True)

        self.hook = construct
        native.__init__ = construct

    def enroll(self, owner, entity_id, entry_id):
        if self.native.__dict__.get("__init__") is not self.hook:
            raise ValueError("ESPHome constructor guard was replaced")
        key = id(owner.hass), entry_id
        existing = self.owners.get(key)
        if existing is not None:
            previous, previous_entity = existing
            if previous is owner:
                if previous_entity != entity_id:
                    raise ValueError("Multiple satellites share one ESPHome entry")
                return
            if not previous._closed or previous.entry is not owner.entry:
                raise ValueError("Satellite already belongs to another protected entry")
        self.owners[key] = owner, entity_id

    def release(self, owner, retained):
        for key, (current, entity_id) in tuple(self.owners.items()):
            if current is owner and entity_id not in retained:
                self.owners.pop(key)
        if not self.owners:
            # Never overwrite another integration's newer constructor hook.
            if self.native.__dict__.get("__init__") is self.hook:
                if self.previous is None:
                    delattr(self.native, "__init__")
                else:
                    self.native.__init__ = self.previous
            if _GUARDS.get(self.native) is self:
                _GUARDS.pop(self.native)


def enroll_constructor(native, owner, entity_id, entry_id):
    """Keep closed owners enrolled through reload; explicit removal releases them."""
    guard = _GUARDS.get(native)
    if guard is None:
        guard = _GUARDS[native] = _ConstructorGuard(native)
    guard.enroll(owner, entity_id, entry_id)
    return guard
