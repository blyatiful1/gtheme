# Maintainer: blyatiful1 <https://github.com/blyatiful1>
#
# Arch package for gtheme. No meson anywhere: the wheel already carries the
# launcher entry, the store listing and the icons under its `.data/data/share`
# tree, so `python -m installer` puts every one of them in the right place with
# no custom code here (research/packaging.md §2, the waypaper precedent).

pkgname=gtheme
pkgver=2.0.0
pkgrel=1
pkgdesc="Change how your GNOME desktop looks — safely, with one-click undo"
arch=('any')
url="https://github.com/blyatiful1/gtheme"
license=('MIT')
depends=(
  'python'
  'python-gobject'
  'gtk4'
  'libadwaita'
  'python-jinja2'
  'python-pydantic'
  'glib2'
  'dconf'
)
optdepends=(
  'gnome-shell: the desktop gtheme changes'
  'libsoup3: find and install add-ons from extensions.gnome.org'
  'gnome-backgrounds: more wallpapers to choose from'
)
makedepends=('python-build' 'python-installer' 'python-wheel' 'python-hatchling')
checkdepends=('python-pytest')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')  # run updpkgsums when the tag exists

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

check() {
  cd "$pkgname-$pkgver"
  # The tiers that need a real desktop session are never run here: the
  # graphical tier needs a display and the sandbox tier boots its own copy of
  # GNOME. Both are local-only (docs/testing.md).
  python -m pytest -q -m "not gtk and not sandbox"
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
  install -Dm644 README.md "$pkgdir/usr/share/doc/$pkgname/README.md"
}

# No post_install() hook: gtheme ships no settings descriptions of its own for
# glib-compile-schemas to build. It only reads and writes the ones GNOME has
# already installed. If that ever changes, the hook goes here
# (research/packaging.md §4).
