#!/bin/bash
# build-amdgpu.sh - Automates compiling and deploying AMDGPU kernel modules & firmware for Flatcar on Karnataka
set -eo pipefail

KARNATAKA_IP="192.168.0.6"
FLATCAR_VER="4593.2.1"
KVER="6.12.87-flatcar"
PERSIST_DIR="/var/lib/state"
IMAGE_PATH="${PERSIST_DIR}/flatcar_developer_container.bin"

echo "========================================================="
echo " Starting Automated AMDGPU Driver Build Pipeline"
echo "========================================================="

# 1. Check if the Flatcar Developer Container is already downloaded on Karnataka
echo "Checking for Developer Container on Karnataka..."
CONTAINER_EXISTS=$(ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "[ -f ${IMAGE_PATH} ] && echo 'true' || echo 'false'")

if [ "${CONTAINER_EXISTS}" == "false" ]; then
  echo "Developer Container not found. Downloading Flatcar ${FLATCAR_VER} SDK image (approx. 600MB)..."
  # Download and decompress directly to Karnataka's persistent NVMe
  ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "
    sudo mkdir -p ${PERSIST_DIR}
    sudo curl -sSL -o ${IMAGE_PATH}.bz2 https://stable.release.flatcar-linux.net/amd64-usr/${FLATCAR_VER}/flatcar_developer_container.bin.bz2
    echo 'Decompressing image...'
    sudo bunzip2 -f ${IMAGE_PATH}.bz2
    sudo chmod 600 ${IMAGE_PATH}
    echo 'Developer Container successfully prepared!'
  "
else
  echo "Developer Container image already exists on Karnataka. Skipping download."
fi

# 2. Download AMD Strix Halo (gfx1151*) firmware blobs directly to Karnataka
echo "Downloading AMD Strix Halo (gfx1151*) firmware blobs..."
FW_BASE_URL="https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/plain/amdgpu"
FW_FILES=(
  "gfx1151_mec.bin"
  "gfx1151_mec2.bin"
  "gfx1151_me.bin"
  "gfx1151_pfp.bin"
  "gfx1151_rlc.bin"
  "gfx1151_sdma.bin"
  "gfx1151_vcn.bin"
  "psp_14_3_3_asd.bin"
  "psp_14_3_3_ta.bin"
  "psp_14_3_3_toc.bin"
)

# Create firmware staging dir on Karnataka
ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "sudo mkdir -p /var/lib/state/firmware /var/lib/state/firmware_work"

for fw in "${FW_FILES[@]}"; do
  echo "  - Fetching ${fw}..."
  ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "sudo curl -sSL -o /var/lib/state/firmware/${fw} ${FW_BASE_URL}/${fw}"
done

# 3. Copy host's pre-built Module.symvers to /var/lib/state for container compile access
echo "Staging pre-built Module.symvers from host..."
ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "sudo cp /lib/modules/${KVER}/build/Module.symvers /var/lib/state/Module.symvers"

# 4. Execute compilation inside systemd-nspawn on Karnataka
echo "Orchestrating module compilation inside systemd-nspawn..."

# Prepare persistent folders on host NVMe to bypass container storage limitations (avoid No Space Left on Device errors)
ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "
  sudo mkdir -p /var/lib/state/usr_src /var/lib/state/portage_tmp /var/lib/state/portage_lib /var/lib/state/portage_db /var/lib/state/portage_log /var/lib/state/modules /var/lib/state/modules_work
  sudo chmod 777 /var/lib/state/usr_src /var/lib/state/portage_tmp /var/lib/state/portage_lib /var/lib/state/portage_db /var/lib/state/portage_log
"

# Execute nspawn mounting all potential storage-heavy directories to the host NVMe SSD
ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "
  sudo systemd-nspawn --quiet --keep-unit --register=no --image=${IMAGE_PATH} \
    --bind=${PERSIST_DIR}:/build \
    --bind=/var/lib/state/usr_src:/usr/src \
    --bind=/var/lib/state/portage_tmp:/var/tmp/portage \
    --bind=/var/lib/state/portage_lib:/var/lib/portage \
    --bind=/var/lib/state/portage_db:/var/db \
    --bind=/var/lib/state/portage_log:/var/log \
    /bin/bash -c '
    set -eo pipefail
    echo \"Synchronizing Portage trees...\"
    emerge-gitclone

    echo \"Downloading matching kernel sources...\"
    emerge -gKv --nodeps coreos-sources

    cd /usr/src/linux
    echo \"Configuring kernel build...\"
    gzip -cd /proc/config.gz > .config

    # Enable AMDGPU and DRM helper module dependencies
    ./scripts/config --module CONFIG_DRM_AMDGPU
    ./scripts/config --module CONFIG_DRM_SCHED
    ./scripts/config --module CONFIG_DRM_TTM
    ./scripts/config --module CONFIG_DRM_DISPLAY_DP_HELPER
    ./scripts/config --module CONFIG_DRM_DISPLAY_HELPER

    make olddefconfig
    make modules_prepare

    echo \"Injecting pre-built kernel symbols (Module.symvers)...\"
    cp /build/Module.symvers .

    echo \"Compiling GPU DRM and AMDGPU modules (this may take a few minutes)...\"
    make -j\$(nproc) M=drivers/gpu/drm modules

    echo \"Staging compiled modules to host persistent directory...\"
    TARGET_DIR=\"/build/modules/${KVER}/kernel/drivers/gpu/drm\"
    mkdir -p \"\${TARGET_DIR}\"
    
    # Copy all compiled .ko files as compressed .ko.xz
    find drivers/gpu/drm/ -name \"*.ko\" | while read -r ko; do
      xz -c \"\${ko}\" > \"\${TARGET_DIR}/\$(basename \${ko}).xz\"
    done
    echo \"Staging complete!\"
  '
"

# 5. Run depmod on Karnataka to register the newly built modules
echo "Registering modules on Karnataka..."
ssh -o StrictHostKeyChecking=no core@${KARNATAKA_IP} "
  sudo mkdir -p /var/lib/state/lib
  sudo ln -sf ../modules /var/lib/state/lib/modules
  sudo depmod -a -b /var/lib/state
  echo 'depmod completed successfully!'
"

# 6. Re-generate Ignition configuration on Bihar PXE server
echo "Re-generating secure Ignition configuration on Bihar PXE server..."
bash /home/james/dotfiles/karnataka/generate-ignition.sh

echo "========================================================="
echo " SUCCESS: AMDGPU Driver & Strix Halo Firmware Deployed!"
echo " Please reboot Karnataka now to load the GPU in Kubernetes."
echo "========================================================="
