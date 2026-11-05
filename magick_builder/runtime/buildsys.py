"""Options that keep upstream build systems inside this build's own inputs."""

from __future__ import annotations

# CMake's user and system package registries (~/.cmake/packages, and
# /usr/local/share/cmake/packages-style entries) are searched by every
# find_package() call. A registry entry left by an unrelated project on this
# host could satisfy a dependency that must come from the workspace, so both
# are off for every CMake configure.
CMAKE_NO_PACKAGE_REGISTRY_OPTIONS = (
    "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF",
    "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
    "-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF",
    "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON",
)
# Meson never downloads a subproject in its place: a missing workspace .pc must
# fail the configure, not fetch and build some other copy of the dependency.
MESON_NO_DOWNLOAD_OPTIONS = ("--wrap-mode=nofallback",)
