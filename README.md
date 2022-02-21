# Artwork Dump

Artwork Dump is an add-on for Kodi that downloads artwork for media in your video and music libraries
into your media file system. It only downloads artwork already added to your libraries by scrapers,
NFO files, or other add-ons. Kodi 19 Matrix only.

## Usage

Run from "Program Add-ons" to download artwork for all video or music library items. It can also be
configured to download artwork automatically after library updates.

## Installation

Install my [dev repository][1] to get updates delivered to you automatically. After the repo is
installed, Artwork Dump can be installed from "Program add-ons". Artwork Dump can also be installed
with a [single zip file][2], but you will have to update manually.

[1]: https://github.com/rmrector/repository.rector.stuff/raw/python3/latest/repository.rector.stuff-latest.zip
[2]: https://github.com/rmrector/repository.rector.stuff/raw/python3/latest/script.artwork.dump-latest.zip

## Motivation

This saves full quality artwork to the file system in the same format that Kodi exports to and imports
from (See wiki for local file naming convention, [example for movie artwork][3]). Save image files
locally to speed up library scanning on a new device or a refreshed library, reduce network load,
and persist your preferred artwork with a longer life than URLs to web services - they occasionally change.

Prefer this over exporting artwork with Kodi - this will download the original artwork while Kodi
exports images re-encoded to be optimized for GUI usage.

Call it a trimmed-down version of Artwork Beef, it is intended to work in concert with Kodi 19's
full support for extended artwork from scrapers and the file system.

[3]: https://kodi.wiki/view/Movie_artwork
