#!/usr/bin/env bash
# Generate changelog from git log since last tag
# Usage: ./generate_changelog.sh [version]
set -euo pipefail

VERSION="${1:-$(date -u +%Y.%m.%d)}"
LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")

echo "## ${VERSION}"
echo ""

if [ -n "$LAST_TAG" ]; then
    RANGE="${LAST_TAG}..HEAD"
else
    RANGE="HEAD"
fi

# Group commits by type (conventional commits)
echo "### Changes"
git log --pretty=format:"- %s (%h)" "$RANGE" --no-merges 2>/dev/null | \
    grep -v "^$" | head -50 || echo "- Initial release"

echo ""
echo ""
echo "### Docker Images"
echo "- \`ghcr.io/breixopd/spectra-app:${VERSION}\`"
echo "- \`ghcr.io/breixopd/spectra-tools:${VERSION}\`"
