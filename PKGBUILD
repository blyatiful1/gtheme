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
checkdepends=('python-pytest')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
# Pinned against the released v0.1.0 tag tarball. Re-pin on every release:
#   updpkgsums    # (or: makepkg -g) then commit the result
sha256sums=('57e232207d37f7c80cd1e8fd09a1d31eab0f783ca0913d1b9868f97c02ccd417')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

check() {
  cd "$pkgname-$pkgver"
  # tests/conftest.py puts src/ on sys.path, so this runs against the tree.
  python -m pytest -q
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
