#!/bin/bash

# Installation Script for Presign API Service (Python FastAPI)
# This script deploys Python source, creates venv, and installs systemd services
# Usage: sudo ./install.sh [install|uninstall|update|status|start|stop]

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
INSTALL_USER="ubuntu"
INSTALL_DIR="/opt/presign-api"
APP_DIR="$INSTALL_DIR/presign_api"
VENV_DIR="$INSTALL_DIR/venv"
LOG_DIR="/var/log/presign-api"

# Source directories (from extracted release)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_APP_DIR="$RELEASE_DIR/presign_api"
SOURCE_SYSTEM_DIR="$RELEASE_DIR/system"
SOURCE_ETC_DIR="$RELEASE_DIR/etc"
SOURCE_ENV_DIR="$RELEASE_DIR/env"

# Services
SERVICES=(
    "presign-api"
    "envoy-presign-api"
)

check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "Please run as root (use sudo)"
        exit 1
    fi
}

check_user() {
    if ! id "$INSTALL_USER" &>/dev/null; then
        log_warning "User $INSTALL_USER does not exist"
        log_info "Creating user $INSTALL_USER..."
        useradd -m -s /bin/bash "$INSTALL_USER"
        log_success "User created"
    fi
}

check_python() {
    log_info "Checking Python installation..."

    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed. Please install Python 3.10+"
        exit 1
    fi

    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    log_info "Python version: $PYTHON_VERSION"

    # Check if venv module is available
    if ! python3 -c "import venv" &> /dev/null; then
        log_error "Python venv module not found. Install with: apt install python3-venv"
        exit 1
    fi

    log_success "Python check passed"
}

create_directories() {
    log_info "Creating installation directories..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$APP_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p /etc/envoy

    # Set ownership
    chown -R "$INSTALL_USER:$INSTALL_USER" "$INSTALL_DIR" 2>/dev/null || true
    chown -R "$INSTALL_USER:$INSTALL_USER" "$LOG_DIR" 2>/dev/null || true

    log_success "Directories created"
}

install_python_app() {
    log_info "Installing Python application..."

    if [ ! -d "$SOURCE_APP_DIR" ]; then
        log_error "Source app directory not found: $SOURCE_APP_DIR"
        exit 1
    fi

    # Copy Python source files
    cp "$SOURCE_APP_DIR/main.py" "$APP_DIR/"
    cp "$SOURCE_APP_DIR/requirements.txt" "$APP_DIR/"

    chown -R "$INSTALL_USER:$INSTALL_USER" "$APP_DIR"

    log_success "Python source files installed"
}

create_venv() {
    log_info "Creating Python virtual environment..."

    # Remove old venv if exists
    if [ -d "$VENV_DIR" ]; then
        log_info "Removing existing virtual environment..."
        rm -rf "$VENV_DIR"
    fi

    # Create new venv as the install user
    sudo -u "$INSTALL_USER" python3 -m venv "$VENV_DIR"

    log_success "Virtual environment created at $VENV_DIR"
}

install_python_deps() {
    log_info "Installing Python dependencies..."

    # Install requirements using venv pip
    sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install --upgrade pip
    sudo -u "$INSTALL_USER" "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"

    log_success "Python dependencies installed"
}

install_config_files() {
    log_info "Installing configuration files..."

    # Copy envoy config
    if [ -d "$SOURCE_ETC_DIR" ]; then
        for config_file in "$SOURCE_ETC_DIR"/*.yaml; do
            if [ -f "$config_file" ]; then
                cp "$config_file" /etc/envoy/
                chmod 644 "/etc/envoy/$(basename $config_file)"
                log_info "✓ Installed $(basename $config_file) to /etc/envoy/"
            fi
        done
    fi

    # Create .env file if doesn't exist
    create_env_file
}

create_env_file() {
    local env_file="$APP_DIR/.env"

    if [ -f "$env_file" ]; then
        log_info "Environment file already exists at $env_file"
        log_warning "Skipping .env creation to preserve existing configuration"
        return
    fi

    log_info "Creating environment file from template..."

    if [ -f "$SOURCE_ENV_DIR/.env.template" ]; then
        cp "$SOURCE_ENV_DIR/.env.template" "$env_file"
    elif [ -f "$SOURCE_ENV_DIR/.env.example" ]; then
        cp "$SOURCE_ENV_DIR/.env.example" "$env_file"
    else
        # Fallback: create default template
        cat > "$env_file" << 'EOF'
# Presign API Service Configuration

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
    fi

    chown "$INSTALL_USER:$INSTALL_USER" "$env_file"
    chmod 600 "$env_file"

    log_success "Environment file created at $env_file"
    log_warning "IMPORTANT: Edit $env_file with your actual AWS configuration!"
}

install_systemd_services() {
    log_info "Installing systemd service files..."

    if [ ! -d "$SOURCE_SYSTEM_DIR" ]; then
        log_error "Source systemd directory not found: $SOURCE_SYSTEM_DIR"
        exit 1
    fi

    local installed_count=0

    for service_file in "$SOURCE_SYSTEM_DIR"/*.service; do
        if [ -f "$service_file" ]; then
            local service_name=$(basename "$service_file")

            # Update paths in service file to use venv python
            sed -e "s|/opt/presign-api/venv/bin/python|$VENV_DIR/bin/python|g" \
                -e "s|/opt/presign-api/presign_api|$APP_DIR|g" \
                "$service_file" > "/etc/systemd/system/$service_name"

            log_info "✓ Installed $service_name"
            ((installed_count++))
        fi
    done

    # Reload systemd
    systemctl daemon-reload

    log_success "$installed_count systemd services installed"
}

enable_services() {
    log_info "Enabling services..."

    for service in "${SERVICES[@]}"; do
        if systemctl enable "$service" 2>/dev/null; then
            log_info "✓ Enabled $service"
        else
            log_warning "Failed to enable $service (service file may not exist)"
        fi
    done

    log_success "Services enabled"
}

start_services() {
    log_info "Starting services..."

    local start_order=(
        "presign-api"
        "envoy-presign-api"
    )

    for service in "${start_order[@]}"; do
        if systemctl list-unit-files | grep -q "$service.service"; then
            log_info "Starting $service..."
            if systemctl start "$service"; then
                log_success "✓ Started $service"
                sleep 2
            else
                log_error "✗ Failed to start $service"
                log_info "Check logs: journalctl -u $service -n 50"
            fi
        fi
    done

    log_info "Checking service status..."
    sleep 3
    show_status
}

stop_services() {
    log_info "Stopping all Presign API services..."

    for service in "${SERVICES[@]}"; do
        if systemctl is-active "$service" &>/dev/null; then
            systemctl stop "$service"
            log_info "✓ Stopped $service"
        fi
    done

    log_success "All services stopped"
}

restart_services() {
    log_info "Restarting services..."
    stop_services
    sleep 2
    start_services
}

show_status() {
    log_info "Service Status:"
    echo ""

    for service in "${SERVICES[@]}"; do
        if systemctl list-unit-files | grep -q "$service"; then
            local status=$(systemctl is-active "$service" 2>/dev/null || echo "inactive")
            local enabled=$(systemctl is-enabled "$service" 2>/dev/null || echo "disabled")

            if [ "$status" = "active" ]; then
                echo -e "${GREEN}●${NC} $service: $status ($enabled)"
            elif [ "$status" = "failed" ]; then
                echo -e "${RED}●${NC} $service: $status ($enabled)"
            else
                echo -e "${YELLOW}●${NC} $service: $status ($enabled)"
            fi
        fi
    done

    echo ""
    log_info "Useful commands:"
    echo "  View service logs: journalctl -u <service-name> -f"
    echo "  View application logs: tail -f $LOG_DIR/*.log"
    echo "  Restart service: systemctl restart <service-name>"
    echo "  Test API: curl http://localhost:8000/health"
}

uninstall_services() {
    log_warning "Uninstalling Presign API services..."

    # Stop all services
    stop_services

    # Disable services
    for service in "${SERVICES[@]}"; do
        systemctl disable "$service" 2>/dev/null || true
    done

    # Remove systemd files
    for service in "${SERVICES[@]}"; do
        rm -f "/etc/systemd/system/$service.service"
    done

    systemctl daemon-reload

    log_info "Systemd services removed"
    log_warning "Installation directory $INSTALL_DIR preserved"
    log_info "To fully remove, run: rm -rf $INSTALL_DIR $LOG_DIR"
}

update_services() {
    log_info "Updating services..."

    # Stop services
    stop_services

    # Install new Python source and deps
    install_python_app
    install_python_deps
    install_config_files

    # Reload systemd (in case service files changed)
    systemctl daemon-reload

    # Start services
    start_services

    log_success "Update complete"
}

show_installation_summary() {
    echo ""
    log_success "================================"
    log_success "Installation Complete!"
    log_success "================================"
    echo ""

    # Show version info if available
    if [ -f "$RELEASE_DIR/VERSION" ]; then
        cat "$RELEASE_DIR/VERSION"
        echo ""
    fi

    echo "Installation paths:"
    echo "  Application: $APP_DIR"
    echo "  Virtual Env: $VENV_DIR"
    echo "  Config: $APP_DIR/.env"
    echo "  Logs: $LOG_DIR"
    echo "  Systemd: /etc/systemd/system/"
    echo "  Envoy: /etc/envoy/"
    echo ""

    local python_ver=$("$VENV_DIR/bin/python" --version)
    echo "Python: $python_ver"
    echo "Services: $(ls -1 /etc/systemd/system/presign-api*.service /etc/systemd/system/envoy-presign-api.service 2>/dev/null | wc -l) systemd services"
    echo ""
    log_info "Next steps:"
    echo "1. Edit configuration: sudo nano $APP_DIR/.env"
    echo "2. Enable services: sudo ./install.sh enable"
    echo "3. Start services: sudo ./install.sh start"
    echo "4. Check status: sudo ./install.sh status"
    echo "5. Test API: curl http://localhost:8000/health"
    echo ""
}

show_usage() {
    echo "Presign API Service Installation Script"
    echo ""
    echo "Usage: sudo $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  install      Install service (default)"
    echo "  uninstall    Remove all services"
    echo "  update       Update Python source and restart services"
    echo "  start        Start services"
    echo "  stop         Stop all services"
    echo "  restart      Restart all active services"
    echo "  status       Show service status"
    echo "  enable       Enable services to start on boot"
    echo ""
    echo "Examples:"
    echo "  sudo $0 install         # Install everything"
    echo "  sudo $0 start           # Start services"
    echo "  sudo $0 status          # Check service status"
    echo "  sudo $0 update          # Update and restart"
}

install_all() {
    log_info "Starting installation..."
    echo ""

    check_root
    check_user
    check_python
    create_directories
    install_python_app
    create_venv
    install_python_deps
    install_config_files
    install_systemd_services

    echo ""
    log_success "Installation complete!"
    show_installation_summary
}

main() {
    case "${1:-install}" in
        install)
            install_all
            ;;
        uninstall)
            check_root
            uninstall_services
            ;;
        update)
            check_root
            update_services
            ;;
        start)
            check_root
            start_services
            ;;
        stop)
            check_root
            stop_services
            ;;
        restart)
            check_root
            restart_services
            ;;
        status)
            show_status
            ;;
        enable)
            check_root
            enable_services
            ;;
        help|--help|-h)
            show_usage
            ;;
        *)
            log_error "Invalid command: ${1}"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
