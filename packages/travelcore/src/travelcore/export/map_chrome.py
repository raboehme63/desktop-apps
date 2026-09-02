"""Read-only map page chrome: strip, journal, YouTube overlay, overview return."""

from __future__ import annotations

_CHROME_CSS = """
html, body {
  height: 100%;
  margin: 0;
  background: #12151c;
  color: #e8edf5;
  font-family: "Segoe UI", system-ui, sans-serif;
}
.tj-shell {
  --tj-zoom: 1;
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.tj-main {
  display: flex;
  flex: 1;
  min-height: 0;
}
.tj-map-host {
  flex: 1;
  position: relative;
  min-width: 0;
}
.tj-map-host .folium-map {
  width: 100% !important;
  height: 100% !important;
}
.tj-journal {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 10px;
  background: #181c27;
  border-left: 1px solid #2a3142;
}
.tj-journal h2 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: #9aa6b8;
}
.tj-notes {
  flex: 1;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: #1a2030;
  border: 1px solid #2a3142;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.45;
  color: #e8edf5;
}
.tj-notes.tj-empty { color: #7d8798; }
.tj-youtube {
  position: absolute;
  right: 10px;
  bottom: 10px;
  z-index: 500;
  display: flex;
  flex-direction: column;
  gap: 6px;
  pointer-events: none;
}
.tj-youtube a {
  pointer-events: auto;
  display: block;
  width: 108px;
  height: 61px;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.2);
}
.tj-youtube img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.tj-footer {
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
  background: #12151c;
  border-top: 1px solid #2a3142;
}
.tj-zoom {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  width: 168px;
  flex-shrink: 0;
  padding: 8px 14px 10px;
  color: #9aa6b8;
  font-size: 12px;
  user-select: none;
}
.tj-zoom-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tj-zoom-track {
  position: relative;
  flex: 1;
  height: 22px;
}
.tj-zoom-track::before {
  content: "";
  position: absolute;
  left: 33.333%;
  top: 2px;
  width: 3px;
  height: 8px;
  margin-left: -1.5px;
  background: #2eb8a0;
  border-radius: 1px;
  pointer-events: none;
}
.tj-zoom input[type="range"] {
  position: relative;
  width: 100%;
  height: 22px;
  margin: 0;
  background: transparent;
  accent-color: #2eb8a0;
  cursor: pointer;
}
.tj-zoom-val {
  min-width: 44px;
  color: #e8edf5;
}
.tj-strip {
  flex: 1;
  min-width: 0;
  height: max(80px, calc(168px * var(--tj-zoom)));
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  overflow-x: auto;
  overflow-y: hidden;
  cursor: grab;
  user-select: none;
  touch-action: pan-x;
}
.tj-strip.tj-dragging { cursor: grabbing; }
.tj-strip img { pointer-events: none; }
.tj-card {
  position: relative;
  flex: 0 0 auto;
  width: calc(174px * var(--tj-zoom));
  height: calc(104px * var(--tj-zoom));
  border: 0;
  padding: 0;
  cursor: pointer;
  color: #fff;
  background: #243044;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 0 0 1.4px #f4f7fb;
}
.tj-card-movement {
  width: calc(186px * var(--tj-zoom));
  clip-path: polygon(11% 0, 89% 0, 100% 50%, 89% 100%, 11% 100%, 0 50%);
  border-radius: 0;
}
.tj-card.tj-on {
  width: calc(248px * var(--tj-zoom));
  height: calc(148px * var(--tj-zoom));
  box-shadow: 0 0 0 2px #2eb8a0;
}
.tj-card.tj-pin { box-shadow: 0 0 0 2px #e23d3d; }
.tj-card img.tj-card-cover {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.tj-card-fade {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 58%;
  background: linear-gradient(transparent, rgba(8, 12, 18, 0.78));
}
.tj-card-meta {
  position: absolute;
  left: 10px;
  right: 10px;
  bottom: 8px;
  text-align: left;
}
.tj-card-title {
  display: block;
  font-size: calc(14px * var(--tj-zoom));
  font-weight: 600;
  line-height: 1.15;
}
.tj-card.tj-on .tj-card-title { font-size: calc(16px * var(--tj-zoom)); }
.tj-card-when {
  display: block;
  margin-top: 2px;
  font-size: calc(10px * var(--tj-zoom));
  color: #e8edf5;
}
.tj-card-chips {
  position: absolute;
  top: 7px;
  right: 8px;
  display: flex;
  gap: 4px;
}
.tj-chip {
  min-width: 18px;
  padding: 1px 5px;
  border-radius: 999px;
  background: rgba(8, 12, 18, 0.62);
  font-size: calc(10px * var(--tj-zoom));
  line-height: 1.4;
}
.tj-day-badge {
  position: absolute;
  top: 7px;
  left: 8px;
  width: 18px;
  height: 18px;
  border-radius: 4px;
  background: rgba(8, 12, 18, 0.62);
  font-size: 11px;
  line-height: 18px;
}
.tj-lightbox {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 4000;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 10px;
  padding: 28px 36px;
  background: rgba(8, 12, 18, 0.88);
}
.tj-lightbox.tj-open { display: flex; }
.tj-lightbox img {
  max-width: min(96vw, 1920px);
  max-height: calc(100vh - 88px);
  object-fit: contain;
  border-radius: 6px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.55);
}
.tj-lb-cap {
  color: #9aa6b8;
  font-size: 13px;
}
.tj-lb-close {
  position: absolute;
  top: 12px;
  right: 16px;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 8px;
  background: #243044;
  color: #e8edf5;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}
"""

_CHROME_JS = """
(function() {
  var COVER_ZOOM = 14;
  function cards() {
    var cfg = window.traveljournalConfig || {};
    return cfg.timeline || [];
  }
  function findCard(key) {
    var list = cards();
    for (var i = 0; i < list.length; i++) {
      if (list[i].key === key) {
        return list[i];
      }
    }
    return null;
  }
  function invalidateMaps() {
    Object.keys(window).forEach(function(name) {
      var map = window[name];
      if (map && map.invalidateSize && map.getContainer) {
        try { map.invalidateSize(); } catch (err) {}
      }
    });
  }
  function clampZoom(percent) {
    var n = parseInt(percent, 10);
    if (!n || n < 50) {
      n = 50;
    }
    if (n > 200) {
      n = 200;
    }
    return Math.round(n / 5) * 5;
  }
  function applyZoom(percent) {
    var n = clampZoom(percent);
    var shell = document.getElementById('tj-shell');
    if (shell) {
      shell.style.setProperty('--tj-zoom', String(n / 100));
    }
    var val = document.getElementById('tj-zoom-val');
    if (val) {
      val.textContent = n + ' %';
    }
    var slider = document.getElementById('tj-zoom');
    if (slider && slider.value !== String(n)) {
      slider.value = String(n);
    }
    window.traveljournalThumbZoom = n;
    if (window.traveljournalSetThumbZoom) {
      window.traveljournalSetThumbZoom(n);
    }
  }
  function bindZoom() {
    var slider = document.getElementById('tj-zoom');
    if (!slider || slider._tjBound) {
      return;
    }
    slider._tjBound = true;
    slider.addEventListener('input', function() {
      applyZoom(slider.value);
    });
    applyZoom(slider.value || 100);
  }
  function bindStripDrag(host) {
    if (!host || host._tjDragBound) {
      return;
    }
    host._tjDragBound = true;
    var dragging = false;
    var moved = false;
    var startX = 0;
    var startScroll = 0;
    host.addEventListener('pointerdown', function(ev) {
      if (ev.button !== 0) {
        return;
      }
      dragging = true;
      moved = false;
      startX = ev.clientX;
      startScroll = host.scrollLeft;
      host.classList.add('tj-dragging');
      try { host.setPointerCapture(ev.pointerId); } catch (err) {}
    });
    host.addEventListener('pointermove', function(ev) {
      if (!dragging) {
        return;
      }
      var dx = ev.clientX - startX;
      if (Math.abs(dx) > 6) {
        moved = true;
      }
      if (moved) {
        host.scrollLeft = startScroll - dx;
      }
    });
    function endDrag() {
      dragging = false;
      host.classList.remove('tj-dragging');
      host._tjMoved = moved;
      moved = false;
    }
    host.addEventListener('pointerup', endDrag);
    host.addEventListener('pointercancel', endDrag);
    host.addEventListener('click', function(ev) {
      if (host._tjMoved) {
        ev.preventDefault();
        ev.stopPropagation();
        host._tjMoved = false;
      }
    }, true);
    host.addEventListener('wheel', function(ev) {
      if (Math.abs(ev.deltaY) >= Math.abs(ev.deltaX) && ev.deltaY) {
        host.scrollLeft += ev.deltaY;
        ev.preventDefault();
      }
    }, {passive: false});
  }
  function mediaEntry(sourceId) {
    var cfg = window.traveljournalConfig || {};
    var media = cfg.media || {};
    var item = media[String(sourceId)];
    if (item && item.src) {
      return {id: String(sourceId), src: item.src, label: item.label || ''};
    }
    var details = cfg.details || {};
    var keys = Object.keys(details);
    for (var d = 0; d < keys.length; d++) {
      var markers = (details[keys[d]] && details[keys[d]].markers) || [];
      for (var i = 0; i < markers.length; i++) {
        if (String(markers[i].source_file_id) === String(sourceId) && markers[i].preview) {
          return {
            id: String(sourceId),
            src: markers[i].preview,
            label: markers[i].label || ''
          };
        }
      }
    }
    return null;
  }
  function mediaIds() {
    var cfg = window.traveljournalConfig || {};
    var media = cfg.media || {};
    var ids = Object.keys(media);
    if (ids.length) {
      return ids;
    }
    var found = [];
    var details = cfg.details || {};
    Object.keys(details).forEach(function(key) {
      ((details[key] && details[key].markers) || []).forEach(function(item) {
        if (item.source_file_id && item.preview) {
          found.push(String(item.source_file_id));
        }
      });
    });
    return found;
  }
  function openLightbox(sourceId) {
    var entry = mediaEntry(sourceId);
    var box = document.getElementById('tj-lightbox');
    var img = document.getElementById('tj-lb-img');
    var cap = document.getElementById('tj-lb-cap');
    if (!entry || !box || !img) {
      return;
    }
    img.src = entry.src;
    img.alt = entry.label || '';
    if (cap) {
      cap.textContent = entry.label || '';
    }
    box.hidden = false;
    box.classList.add('tj-open');
    box._tjId = String(sourceId);
  }
  function closeLightbox() {
    var box = document.getElementById('tj-lightbox');
    if (!box) {
      return;
    }
    box.hidden = true;
    box.classList.remove('tj-open');
    box._tjId = '';
  }
  function stepLightbox(delta) {
    var box = document.getElementById('tj-lightbox');
    if (!box || !box.classList.contains('tj-open')) {
      return;
    }
    var ids = mediaIds();
    if (ids.length < 2) {
      return;
    }
    var idx = ids.indexOf(String(box._tjId));
    if (idx < 0) {
      idx = 0;
    }
    openLightbox(ids[(idx + delta + ids.length) % ids.length]);
  }
  function bindLightbox() {
    var box = document.getElementById('tj-lightbox');
    var close = document.getElementById('tj-lb-close');
    if (box && !box._tjBound) {
      box._tjBound = true;
      box.addEventListener('click', function(ev) {
        if (ev.target === box) {
          closeLightbox();
        }
      });
    }
    if (close && !close._tjBound) {
      close._tjBound = true;
      close.addEventListener('click', function(ev) {
        ev.preventDefault();
        closeLightbox();
      });
    }
    if (!document._tjLightboxKeys) {
      document._tjLightboxKeys = true;
      document.addEventListener('keydown', function(ev) {
        var host = document.getElementById('tj-lightbox');
        if (!host || !host.classList.contains('tj-open')) {
          return;
        }
        if (ev.key === 'Escape') {
          closeLightbox();
          ev.preventDefault();
        } else if (ev.key === 'ArrowLeft') {
          stepLightbox(-1);
          ev.preventDefault();
        } else if (ev.key === 'ArrowRight') {
          stepLightbox(1);
          ev.preventDefault();
        }
      });
    }
  }
  function installOpenMedia() {
    window.traveljournalShowOriginal = openLightbox;
    window.traveljournalOpenMedia = function(sourceId) {
      openLightbox(sourceId);
    };
  }
  function wrapChrome() {
    var map = document.querySelector('.folium-map');
    if (!map || document.getElementById('tj-shell')) {
      return;
    }
    var shell = document.createElement('div');
    shell.id = 'tj-shell';
    shell.className = 'tj-shell';
    shell.innerHTML =
      '<div class="tj-main">' +
        '<div class="tj-map-host">' +
          '<div class="tj-youtube" id="tj-youtube"></div>' +
        '</div>' +
        '<aside class="tj-journal">' +
          '<h2>Tagebucheintrag</h2>' +
          '<div class="tj-notes tj-empty" id="tj-notes">' +
          'Tagebucheintrag der fokussierten Abschnittskarte</div>' +
        '</aside>' +
      '</div>' +
      '<div class="tj-footer">' +
        '<label class="tj-zoom">Zoom' +
          '<span class="tj-zoom-row">' +
            '<span class="tj-zoom-track">' +
              '<input type="range" id="tj-zoom" min="50" max="200" step="5" value="100">' +
            '</span>' +
            '<span class="tj-zoom-val" id="tj-zoom-val">100 %</span>' +
          '</span>' +
        '</label>' +
        '<div class="tj-strip" id="tj-strip"></div>' +
      '</div>' +
      '<div class="tj-lightbox" id="tj-lightbox" hidden>' +
        '<button type="button" class="tj-lb-close" id="tj-lb-close" aria-label="Schließen">×</button>' +
        '<img id="tj-lb-img" alt="">' +
        '<div class="tj-lb-cap" id="tj-lb-cap"></div>' +
      '</div>';
    map.parentNode.insertBefore(shell, map);
    shell.querySelector('.tj-map-host').insertBefore(map, shell.querySelector('.tj-youtube'));
    window.traveljournalOverlayPad = 72;
    renderStrip();
    bindStripDrag(document.getElementById('tj-strip'));
    bindZoom();
    bindLightbox();
    hookMap();
    installOpenMedia();
    setTimeout(invalidateMaps, 80);
    setTimeout(invalidateMaps, 320);
  }
  function chip(label, count) {
    if (!count) {
      return '';
    }
    return '<span class="tj-chip">' + label + count + '</span>';
  }
  function renderStrip() {
    var host = document.getElementById('tj-strip');
    if (!host) {
      return;
    }
    host.innerHTML = cards().map(function(card) {
      var kind = card.kind || 'stay';
      var cls = 'tj-card tj-card-' + kind + (card.needs_pin ? ' tj-pin' : '');
      var cover = card.cover
        ? '<img class="tj-card-cover" src="' + String(card.cover).replace(/"/g, '&quot;') + '" alt="">'
        : '';
      var badge = kind === 'day' ? '<span class="tj-day-badge">&#128197;</span>' : '';
      var chips = chip('', card.photos) + chip('T', card.tracks) + chip('igc', card.igc)
        + chip('▶', card.youtube_count);
      return '<button type="button" class="' + cls + '" data-key="' +
        String(card.key).replace(/"/g, '') + '">' + cover +
        '<span class="tj-card-fade"></span>' + badge +
        '<span class="tj-card-chips">' + chips + '</span>' +
        '<span class="tj-card-meta"><span class="tj-card-title"></span>' +
        '<span class="tj-card-when"></span></span></button>';
    }).join('');
    var buttons = host.querySelectorAll('.tj-card');
    cards().forEach(function(card, index) {
      var btn = buttons[index];
      if (!btn) {
        return;
      }
      btn.querySelector('.tj-card-title').textContent = card.title || '';
      btn.querySelector('.tj-card-when').textContent = card.time_label || '';
      btn.addEventListener('click', function() { onCardClick(card.key); });
    });
  }
  function focusEntry(key) {
    var card = findCard(key);
    var notes = document.getElementById('tj-notes');
    var tube = document.getElementById('tj-youtube');
    document.querySelectorAll('.tj-card').forEach(function(btn) {
      btn.classList.toggle('tj-on', btn.getAttribute('data-key') === key);
    });
    var on = document.querySelector('.tj-card.tj-on');
    if (on && on.scrollIntoView) {
      on.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
    }
    if (!notes || !tube) {
      return;
    }
    if (!card) {
      notes.textContent = 'Tagebucheintrag der fokussierten Abschnittskarte';
      notes.classList.add('tj-empty');
      tube.innerHTML = '';
      return;
    }
    if (card.notes) {
      notes.textContent = card.notes;
      notes.classList.remove('tj-empty');
    } else {
      notes.textContent = 'Kein Tagebucheintrag für diesen Eintrag';
      notes.classList.add('tj-empty');
    }
    tube.innerHTML = (card.youtube || []).map(function(item) {
      var href = String(item.url || '').replace(/"/g, '&quot;');
      var thumb = String(item.thumb || '').replace(/"/g, '&quot;');
      if (!href) {
        return '';
      }
      var img = thumb
        ? '<img src="' + thumb + '" alt="YouTube">'
        : '<img alt="YouTube">';
      return '<a href="' + href + '" target="_blank" rel="noopener">' + img + '</a>';
    }).join('');
  }
  function onCardClick(key) {
    focusEntry(key);
    var card = findCard(key);
    if (window._tjInDetail) {
      if (card && typeof card.lat === 'number' && window.traveljournalZoomToCover) {
        window.traveljournalZoomToCover(card.lat, card.lon, key, COVER_ZOOM);
      } else if (window.traveljournalCloseSection) {
        window.traveljournalCloseSection();
      }
      window._tjInDetail = false;
      return;
    }
    if (window.traveljournalCenterCover) {
      window.traveljournalCenterCover(key);
    }
  }
  function wrap(name, after) {
    var orig = window[name];
    if (typeof orig !== 'function' || orig._tjChrome) {
      return false;
    }
    var wrapped = function() {
      var result = orig.apply(this, arguments);
      after.apply(this, arguments);
      return result;
    };
    wrapped._tjChrome = true;
    window[name] = wrapped;
    return true;
  }
  function hookMap() {
    wrap('traveljournalShowDetail', function() { window._tjInDetail = true; });
    wrap('traveljournalCloseSection', function() { window._tjInDetail = false; });
    wrap('traveljournalZoomToCover', function() { window._tjInDetail = false; });
    wrap('traveljournalExpand', function(key) { focusEntry(key); });
    installOpenMedia();
  }
  function boot(tries) {
    wrapChrome();
    hookMap();
    bindZoom();
    bindLightbox();
    installOpenMedia();
    if (tries > 0 && typeof window.traveljournalExpand !== 'function') {
      setTimeout(function() { boot(tries - 1); }, 50);
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { boot(120); });
  } else {
    boot(120);
  }
})();
"""


def chrome_markup(*, title: str = "") -> str:
    """CSS and boot script for the read-only map page around a Folium map."""

    del title
    return f"<style>{_CHROME_CSS}</style>\n<script>{_CHROME_JS}</script>\n"
