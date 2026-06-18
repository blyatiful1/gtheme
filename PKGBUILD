# Maintainer: blyatiful1
pkgname=gtheme
pkgver=0.1.0
pkgrel=1
pkgdesc="A GNOME desktop theme system: download, apply, switch, and author full-desktop themes from a palette"
arch=('any')
url="https://github.com/blyatiful1/gtheme"
license=('MIT')
# glib2 provides gsettings; dconf is core to applying/restoring settings.
depends=('python>=3.11' 'python-jinja2' 'python-pydantic' 'glib2' 'dconf')
optdepends=('gnome-shell: desktop integration'
            'git: install themes from remote repos')
makedepends=('python-hatchling' 'python-build' 'python-installer' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
# A release tarball's hash cannot exist before the tag is pushed. The maintainer
# MUST pin the real checksum per release once v$pkgver is tagged upstream:
#   updpkgsums    # (or: makepkg -g) then commit the result
# 'SKIP' is a placeholder only and disables integrity verification — do not ship it.
sha256sums=('SKIP')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
