# Vendored fonts

These Latin WOFF2 assets are self-hosted through `next/font/local` so production builds do not depend on Google Fonts network access.

| Local file | Family and range | SHA-256 | Official distribution URL | License |
| --- | --- | --- | --- | --- |
| `caprasimo-latin-400.woff2` | Caprasimo 400, Latin | `8be0594f223844d398b066640ab4303555978a8a72c6558ff769251007bd431a` | `https://fonts.gstatic.com/s/caprasimo/v6/esDT31JQOPuXIUGBp72Ukp8DOJKuGA.woff2` | `licenses/Caprasimo-OFL.txt` |
| `figtree-latin-variable.woff2` | Figtree 300–900, Latin | `8330490a01c60c196eae00b823de8102275aaa5862e7b76a7af21b8745338928` | `https://fonts.gstatic.com/s/figtree/v9/_Xms-HUzqDCFdgfMm4S9DaRvzig.woff2` | `licenses/Figtree-OFL.txt` |
| `geist-mono-latin-variable.woff2` | Geist Mono 100–900, Latin | `5f3d6ad60f29d6cb708414ec6887163d63bf197377ef5417d2483ff31ace6c3b` | `https://fonts.gstatic.com/s/geistmono/v6/or3nQ6H-1_WfwkMZI_qYFrcdmhHkjko.woff2` | `licenses/Geist-Mono-OFL.txt` |

The URLs were resolved from the official Google Fonts CSS2 API using a WOFF2-capable browser user agent on 2026-08-03. To update an asset, resolve the current Latin URL again, download it with HTTP failure handling, verify the `wOF2` magic bytes and SHA-256 digest, then run the production build.
