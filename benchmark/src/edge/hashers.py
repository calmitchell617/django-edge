"""Password hashing for disposable, randomly generated benchmark accounts."""

import base64
import sys

from django.contrib.auth.hashers import PBKDF2PasswordHasher


class BenchmarkPasswordHasher(PBKDF2PasswordHasher):
    # Hosted Workers caps PBKDF2 iterations. Keep normal salted Django hashes,
    # with a runtime-compatible work factor for this test-only application.
    # This is not a production credential-storage recommendation.
    iterations = 100_000

    def encode(self, password, salt, iterations=None):
        if sys.platform != "emscripten":
            return super().encode(password, salt, iterations)
        # Use the platform crypto API explicitly: the hosted Python hashlib
        # PBKDF2 bridge is not available consistently across runtime versions.
        from js import Object, Uint8Array, crypto
        from pyodide.ffi import run_sync, to_js

        self._check_encode_args(password, salt)
        iterations = iterations or self.iterations
        key = run_sync(
            crypto.subtle.importKey(
                "raw", to_js(password.encode()), "PBKDF2", False, to_js(["deriveBits"])
            )
        )
        derived = run_sync(
            crypto.subtle.deriveBits(
                to_js(
                    {
                        "name": "PBKDF2",
                        "salt": salt.encode(),
                        "iterations": iterations,
                        "hash": "SHA-256",
                    },
                    dict_converter=Object.fromEntries,
                ),
                key,
                256,
            )
        )
        encoded = base64.b64encode(bytes(Uint8Array.new(derived).to_py())).decode("ascii")
        return f"{self.algorithm}${iterations}${salt}${encoded}"
