"""Where updates come from, and the key they must be signed with.

Written by `tools\\release.py configure` / `keygen`. Until both are set, the updater
says "updates aren't set up yet" and never downloads anything.
"""

# https://github.com/<owner>/<repo>/releases/latest/download/manifest.json
MANIFEST_URL: str | None = 'https://github.com/dielman/dielify-releases/releases/latest/download/manifest.json'

# Ed25519 public key (PEM). Only installers listed in a manifest signed with the
# matching private key (kept on Josh's PC, never in the repository) are installed.
PUBLIC_KEY_PEM: str | None = '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAZGGEqjg1EgHemA2gC+ySNnkXKWNLwg7iebsapFaNPbA=\n-----END PUBLIC KEY-----'