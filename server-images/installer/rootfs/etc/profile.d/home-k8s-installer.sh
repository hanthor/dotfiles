if [ "$(id -u)" = 0 ] && [ -t 0 ]; then
    printf '\nHome Kubernetes installer (live media, root console).\n'
    printf 'Run: bootc-installer-tui\n'
    printf 'Image: Custom URL -> oci:/usr/share/home-k8s/payload\n'
    printf 'Set the hostname to the node named below. All selected disk data is erased.\n'
    cat /etc/hostname
    printf 'SSH-key import is not serialized by this TUI; add keys after installation.\n\n'
fi
