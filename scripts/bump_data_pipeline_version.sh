#!/bin/bash

# This will bump the poetry version and add a git tag. Really useful for CD
# Assuming this is run from the data-pipeline directory

# Run Poetry version bump (e.g., patch, minor, major)
poetry version $1

# Get the new version from pyproject.toml
NEW_VERSION=$(poetry version -s)

# Create a Git tag with the new version
git tag "v$NEW_VERSION"