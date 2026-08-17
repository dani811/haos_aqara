# Contract: AqaraU200Client

The Home Assistant integration owns this boundary. External protocol libraries are adapted to it rather than imported by entities.

```python
class AqaraU200Client(Protocol):
    @property
    def control_enabled(self) -> bool: ...

    async def async_lock(self) -> None: ...
    async def async_unlock(self) -> None: ...
```

## Contract rules

- Methods are async from the Home Assistant caller perspective.
- Implementations must not expose session keys, auth headers, KDF inputs, raw frames, or cloud payloads to entities.
- The real adapter returns `control_enabled=True` only for confirmed lock/unlock operations.
- Each method resolves a connectable device through Home Assistant, establishes a fresh connection, wraps it with `U200Client.from_gatt()`, executes once, and disconnects.
- The adapter maps library-specific errors to integration-owned typed exceptions with sanitized messages.
- An operation is never retried after the protocol call begins; no optimistic entity state is written.
- The runtime serializes Home Assistant calls; the protocol library remains responsible for rejecting accidental concurrent same-device sessions at its own boundary.
