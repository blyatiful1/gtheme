# Maintainer: crocco
pkgname=gtheme
pkgver=0.1.0
pkgrel=1
pkgdesc="A GNOME desktop theme system: download, apply, switch, and author full-desktop themes from a palette"
arch=('any')
url="https://github.com/crocco/gtheme"
license=('MIT')
depends=('python>=3.11' 'python-jinja2' 'python-pydantic')
optdepends=('dconf: GNOME extension settings'
            'gnome-shell: desktop integration'
            'git: install themes from remote repos')
makedepends=('python-hatchling' 'python-build' 'python-installer' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}
