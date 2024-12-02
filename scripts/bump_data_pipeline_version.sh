#!/bin/bash

# Ensure the script exits on errors
set -e

# Ensure this script is run from the 'data-pipeline' directory

# Run Poetry version bump (e.g., patch, minor, major)
poetry version $1

# Get the new version from pyproject.toml
NEW_VERSION=$(poetry version -s)

# Commit the updated pyproject.toml (and lock file if changed)
git reset
git add pyproject.toml poetry.lock
git commit -m "Bump version to $NEW_VERSION"

# Push the updated code to the remote repository
git push origin main  # or your current branch

# Create a Git tag with the new version
git tag "v$NEW_VERSION"

# Push the Git tag to the remote repository
git push origin "v$NEW_VERSION"
