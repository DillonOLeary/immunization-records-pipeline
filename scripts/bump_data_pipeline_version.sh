#!/bin/bash
# THIS IS FOR REFERENCE ONLY

# This will bump the poetry version and add a git tag. Really useful for CD
# Assuming this is run from the data-pipeline directory

# Run Poetry version bump (e.g., patch, minor, major)
# poetry version $1

# Get the new version from pyproject.toml
# NEW_VERSION=$(poetry version -s)

# The code needs to be pushed here or else pypi will not
# get the newest package version for the release

# Create a Git tag with the new version
# git tag "v$NEW_VERSION"

# Push the Git tag to the remote repository
# git push origin "v$NEW_VERSION"