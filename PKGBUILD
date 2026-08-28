# Maintainer: blyatiful1 <https://github.com/blyatiful1>
#
# Arch package for gtheme. No meson anywhere: the wheel already carries the
# launcher entry, the store listing and the icons under its `.data/data/share`
# tree, so `python -m installer` puts every one of them in the right place with
# no custom code here (research/packaging.md §2, the waypaper precedent).
#
# THIS FILE BUILDS A RELEASE: `makepkg` fetches
# $url/archive/refs/tags/v$pkgver.tar.gz, so it builds from the moment that tag
# is pushed and not one minute before. The checksum below is still `SKIP`, which
# means the download is not verified — whoever cuts the tag runs `updpkgsums`
# and replaces it in the same breath. To build the checkout you have instead,
# use PKGBUILD-git beside this file.

pkgname=gtheme
# Must equal `__version__` in src/gtheme/__init__.py and the newest <release>
# in data/*.metainfo.xml, or `pacman -Qi` and the About dialog name different
# builds and no bug report can be pinned to one.
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
# dbus supplies dbus-run-session, which check() wraps the suite in; dconf and
# glib2 are already runtime depends and provide the dconf/gsettings/
# glib-compile-schemas binaries the dconf tier needs.
checkdepends=('python-pytest' 'dbus')
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('278132b5157be7f6887fea5d350478a89a219285c9271f2358a0c26dbf0013d5')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

check() {
  cd "$pkgname-$pkgver"
  # The tiers that need a real desktop session are never run here: the
  # graphical tier needs a display and the sandbox tier boots its own copy of
  # GNOME. Both are local-only (docs/testing.md).
  #
  # dbus-run-session is not optional. A clean build chroot has no
  # DBUS_SESSION_BUS_ADDRESS, and the `dconf` tier that this selection includes
  # needs a session bus to activate dconf-service; without one those tests skip
  # themselves and the check proves nothing.
  #
  # PYTHONPATH is not optional either, and it is the environment variable and
  # not pytest's `pythonpath` ini setting on purpose. gtheme is NOT installed
  # at this point — build() only built a wheel — and nothing else puts `src/`
  # on the path, so without this every test module dies at collection with
  # `ModuleNotFoundError: No module named 'gtheme'` and makepkg aborts here.
  # The ini setting would fix collection only: several tests re-import gtheme
  # in a *fresh interpreter* (`gtheme.core` must load with no GTK, the ego
  # client must load with no desktop libraries at all), and a child process
  # inherits the variable but not pytest's in-process sys.path.
  PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}" \
    dbus-run-session -- python -m pytest -q -m "not gtk and not sandbox"
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
