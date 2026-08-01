#!/usr/bin/env bash
# Container validation matrix over the supported OS images.
#
#   bash tests/run-container-matrix.sh <lint|apt|resolve|full> [image ...]
#
# Levels:
#   lint    - lint gate + offline test suite inside each image
#   apt     - required-package availability gate inside each image
#   resolve - every upstream version resolver inside each image (network)
#   full    - complete non-root build (NOPASSWD sudo) driven end to end;
#             success implies the script's own staged+live validation and
#             delegate assertions all passed
#
# Containers are kept alive (named magick-matrix-*) so a failed full build
# can be rerun incrementally after a fix (completion markers survive).
# Remove them with: docker rm -f $(docker ps -aq --filter name=magick-matrix-)

set -o pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"

level="${1:-}"
case "$level" in
    lint|apt|resolve|full) ;;
    *)
        echo "usage: run-container-matrix.sh <lint|apt|resolve|full> [image ...]" >&2
        exit 2
        ;;
esac
shift

images=("$@")
[[ "${#images[@]}" -gt 0 ]] || images=(debian:12 debian:13 ubuntu:22.04 ubuntu:24.04)

container_name() {
    printf 'magick-matrix-%s\n' "${1//[^a-zA-Z0-9]/-}"
}

ensure_container() {
    local image="$1" name
    name=$(container_name "$image")
    if ! docker ps --format '{{.Names}}' | grep -qx "$name"; then
        docker rm -f "$name" >/dev/null 2>&1
        docker run -d --name "$name" "$image" sleep infinity >/dev/null || return 1
        docker exec "$name" bash -c '
            set -e
            export DEBIAN_FRONTEND=noninteractive
            apt update -q >/dev/null
            apt install -y -q sudo curl git ca-certificates python3 \
                shellcheck xz-utils bzip2 >/dev/null
            id builder >/dev/null 2>&1 || useradd -m -s /bin/bash builder
            printf "builder ALL=(ALL) NOPASSWD: ALL\n" > /etc/sudoers.d/builder
            chmod 440 /etc/sudoers.d/builder
        ' || return 1
    fi
    # Refresh the repository copy on every invocation so fixes propagate;
    # the builder home (markers, caches) is deliberately preserved.
    docker exec "$name" rm -rf /home/builder/repo
    docker cp -q "$repo_root" "$name:/home/builder/repo"
    docker exec "$name" bash -c 'rm -rf /home/builder/repo/magick-build-script; chown -R builder:builder /home/builder/repo'
}

run_level() {
    local name="$1"
    case "$level" in
        lint)
            docker exec -u builder -w /home/builder/repo -e HOME=/home/builder "$name" \
                bash -c 'python3 run_linter.py && bash tests/test-scripts.sh'
            ;;
        apt)
            docker exec "$name" bash -c 'apt update -q >/dev/null' &&
                docker exec -u builder -w /home/builder/repo -e HOME=/home/builder "$name" \
                    bash tests/check-apt-availability.sh
            ;;
        resolve)
            docker exec -u builder -w /home/builder/repo -e HOME=/home/builder "$name" \
                bash tests/resolve-all-versions.sh
            ;;
        full)
            docker exec -u builder -w /home/builder -e HOME=/home/builder "$name" \
                bash -c 'bash repo/build-magick.sh --no-cleanup </dev/null'
            ;;
    esac
}

overall=0
for image in "${images[@]}"; do
    name=$(container_name "$image")
    printf '===== %s : %s =====\n' "$level" "$image"
    if ! ensure_container "$image"; then
        printf '===== %s : %s : CONTAINER SETUP FAILED =====\n' "$level" "$image" >&2
        overall=1
        continue
    fi
    if run_level "$name"; then
        printf '===== %s : %s : OK =====\n' "$level" "$image"
    else
        printf '===== %s : %s : FAILED =====\n' "$level" "$image" >&2
        overall=1
    fi
done
exit "$overall"
