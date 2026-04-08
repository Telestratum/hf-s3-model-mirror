#!/bin/bash

# Package Script for Presign API Service (Python)
# Creates release archive with Python source files
# Usage: ./package-release.sh [version]
# Example: ./package-release.sh v1.2.0

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration
VERSION="${1:-v1.2.0}"
BUILD_DIR="$(pwd)/../.."
PROJECT_DIR="$BUILD_DIR"
OUTPUT_BASE="$BUILD_DIR/presign-api-release-$VERSION"
OUTPUT_APP="$OUTPUT_BASE/presign_api"
OUTPUT_SYSTEM="$OUTPUT_BASE/system"
OUTPUT_ETC="$OUTPUT_BASE/etc"
OUTPUT_ENV="$OUTPUT_BASE/env"
OUTPUT_SCRIPTS="$OUTPUT_BASE/scripts"

check_prerequisites() {
    log_info "Checking prerequisites..."

    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed."
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    log_info "Python version: $PYTHON_VERSION"

    log_success "Prerequisites check passed"
}

clean_release_directory() {
    log_info "Cleaning previous release directory..."

    if [ -d "$OUTPUT_BASE" ]; then
        rm -rf "$OUTPUT_BASE"
        log_info "Removed existing release directory"
    fi
}

create_release_structure() {
    log_info "Creating release directory structure..."

    mkdir -p "$OUTPUT_APP"
    mkdir -p "$OUTPUT_SYSTEM"
    mkdir -p "$OUTPUT_ETC"
    mkdir -p "$OUTPUT_ENV"
    mkdir -p "$OUTPUT_SCRIPTS"

    log_success "Directory structure created"
}

copy_python_source() {
    log_info "Copying Python source files..."

    local source_dir="$PROJECT_DIR/presign_api"

    if [ ! -d "$source_dir" ]; then
        log_error "presign_api directory not found: $source_dir"
        exit 1
    fi

    # Copy Python files and requirements.txt
    cp "$source_dir/main.py" "$OUTPUT_APP/"
    cp "$source_dir/requirements.txt" "$OUTPUT_APP/"

    # Copy .env.example if exists
    if [ -f "$source_dir/.env.example" ]; then
        cp "$source_dir/.env.example" "$OUTPUT_ENV/"
    fi

    log_success "Python source files copied"
}

copy_systemd_services() {
    log_info "Copying systemd service files..."

    local systemd_source="$(pwd)/services"

    if [ ! -d "$systemd_source" ]; then
        log_error "Systemd services directory not found: $systemd_source"
        exit 1
    fi

    local count=0
    for service_file in "$systemd_source"/*.service; do
        if [ -f "$service_file" ]; then
            local service_name=$(basename "$service_file")
            cp "$service_file" "$OUTPUT_SYSTEM/$service_name"
            log_info "✓ Copied $(basename $service_file)"
            count=$((count + 1))
        fi
    done

    log_success "$count systemd service files copied"
}

copy_envoy_config() {
    log_info "Copying Envoy configuration..."

    local envoy_dir="$(pwd)/envoy"
    local envoy_config_main="$envoy_dir/envoy-presign-api.yaml"
    local envoy_config_presign="$PROJECT_DIR/presign_api/envoy.yaml"

    # Try from envoy subdirectory first
    if [ -f "$envoy_config_main" ]; then
        cp "$envoy_config_main" "$OUTPUT_ETC/"
        log_success "✓ Envoy configuration copied from deploy-automation/envoy/"
    # Try from presign_api directory
    elif [ -f "$envoy_config_presign" ]; then
        cp "$envoy_config_presign" "$OUTPUT_ETC/envoy-presign-api.yaml"
        log_success "✓ Envoy configuration copied from presign_api/"
    else
        log_warning "Envoy configuration not found"
    fi
}

create_env_template() {
    log_info "Creating environment template..."

    cat > "$OUTPUT_ENV/.env.template" << 'EOF'
# Presign API Service Environment Configuration
# Copy this file to .env and edit with your actual configuration

# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key

# S3 Configuration
S3_BUCKET=your-bucket-name
S3_PREFIX=models/

# Presigned URL Configuration
PRESIGN_EXPIRATION=3600

# API Configuration
API_PORT=8000
API_HOST=0.0.0.0

# Logging
LOG_LEVEL=info
LOG_FILE=/var/log/presign-api/presign-api.log
EOF

    log_success "Environment template created"
}

create_version_file() {
    log_info "Creating version file..."

    cat > "$OUTPUT_BASE/VERSION" << EOF
Version: $VERSION
Type: Python FastAPI Service
Build Date: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
Git Commit: $(cd $BUILD_DIR && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
Git Branch: $(cd $BUILD_DIR && git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
Packaged By: $(whoami)@$(hostname)
EOF

    log_success "Version file created"
}

create_install_script() {
    log_info "Creating install script..."

    if [ -f "$(pwd)/install-release.sh" ]; then
        cp "$(pwd)/install-release.sh" "$OUTPUT_SCRIPTS/install.sh"
        chmod +x "$OUTPUT_SCRIPTS/install.sh"
        log_success "✓ Install script copied"
    else
        log_warning "install-release.sh not found"
    fi
}

create_uninstall_script() {
    log_info "Creating uninstall script..."

    cat > "$OUTPUT_SCRIPTS/uninstall.sh" << 'EOF'
#!/bin/bash

# Uninstall Script for Presign API Service
# Usage: sudo ./uninstall.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

log_warning "Uninstalling Presign API service..."
echo ""

# Stop services
log_info "Stopping services..."
systemctl stop presign-api 2>/dev/null || true
systemctl stop envoy-presign-api 2>/dev/null || true

# Disable services
log_info "Disabling services..."
systemctl disable presign-api 2>/dev/null || true
systemctl disable envoy-presign-api 2>/dev/null || true

# Remove systemd files
log_info "Removing systemd service files..."
rm -f /etc/systemd/system/presign-api.service
rm -f /etc/systemd/system/envoy-presign-api.service

# Reload systemd
systemctl daemon-reload

# Remove envoy config
log_info "Removing envoy configuration..."
rm -f /etc/envoy/envoy-presign-api.yaml

log_success "Services uninstalled"
echo ""
log_info "Application files preserved at /opt/presign-api/"
log_info "Logs preserved at /var/log/presign-api/"
echo ""
log_warning "To completely remove all files, run:"
echo "  sudo rm -rf /opt/presign-api"
echo "  sudo rm -rf /var/log/presign-api"
EOF

    chmod +x "$OUTPUT_SCRIPTS/uninstall.sh"
    log_success "✓ Uninstall script created"
}

create_archive() {
    log_info "Creating tar.gz archive..."

    cd "$BUILD_DIR"

    local archive_name="presign-api-release-$VERSION.tar.gz"

    # Remove old archive if exists
    if [ -f "$archive_name" ]; then
        rm -f "$archive_name"
        log_info "Removed existing archive"
    fi

    # Create archive
    tar czf "$archive_name" "presign-api-release-$VERSION"

    if [ $? -eq 0 ]; then
        log_success "Archive created: $archive_name"
    else
        log_error "Failed to create archive"
        exit 1
    fi

    # Generate checksum
    sha256sum "$archive_name" > "$archive_name.sha256"
    log_success "Checksum generated: $archive_name.sha256"
}

show_package_summary() {
    echo ""
    log_success "================================"
    log_success "Package Complete!"
    log_success "================================"
    echo ""
    echo "Version: $VERSION"
    echo "Archive: $BUILD_DIR/presign-api-release-$VERSION.tar.gz"
    echo ""

    local archive_size=$(du -sh "$BUILD_DIR/presign-api-release-$VERSION.tar.gz" 2>/dev/null | awk '{print $1}')
    echo "Archive size: ${archive_size:-unknown}"
    echo ""

    echo "Release structure:"
    echo "presign-api-release-$VERSION/"
    echo "├── presign_api/      (Python source files)"
    echo "├── system/           (systemd service files)"
    echo "├── etc/              (Envoy configuration)"
    echo "├── env/              (environment template)"
    echo "├── scripts/          (install/uninstall scripts)"
    echo "└── VERSION           (build metadata)"
    echo ""

    log_info "Next steps:"
    echo "1. Transfer: scp presign-api-release-$VERSION.tar.gz ubuntu@server:/home/ubuntu/releases/"
    echo "2. On server: cd ~/releases && tar xzf presign-api-release-$VERSION.tar.gz"
    echo "3. Install: cd presign-api-release-$VERSION/scripts && sudo ./install.sh"
}

main() {
    log_info "Presign API Service Package Script"
    log_info "Version: $VERSION"
    echo ""

    check_prerequisites
    clean_release_directory
    create_release_structure
    copy_python_source
    copy_systemd_services
    copy_envoy_config
    create_env_template
    create_version_file
    create_install_script
    create_uninstall_script
    create_archive
    show_package_summary
}

main "$@"
