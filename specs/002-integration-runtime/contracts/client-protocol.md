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
- An implementation with incomplete/unsafe protocol support returns `control_enabled=False`.
- When disabled, operations raise the integration-owned backend-not-ready exception and MUST have no side effects.
- Future real adapters map library-specific errors to integration-owned typed exceptions.
- The runtime serializes Home Assistant calls; the protocol library remains responsible for rejecting accidental concurrent same-device sessions at its own boundary.
