"""One visual contract for reconciled V3 executions on all V3 charts.

Native Lightweight Charts v5 supports arrowUp/arrowDown but no *triangle-only*
shape. We draw small price/time-anchored SVG triangles for entries/partial
reductions, and neutral gray squares only for confirmed full FLAT closes;
no DOM hit targets, no change to broker orders, candle data, or AI markers.
Use the same helper from the inspector, TradingDesk full chart and 1s updater.
"""

V3_EXECUTION_TRIANGLE_JS = r"""
function createPgV3TradeTriangleLayer(chart, priceSeries, root) {
    const ns = 'http://www.w3.org/2000/svg';
    const layer = document.createElementNS(ns, 'svg');
    layer.setAttribute('aria-label', 'V3-posisjoner: kjøp/salg som trekanter og flat som grå firkant');
    layer.classList.add('pg-v3-execution-triangles');
    Object.assign(layer.style, {
        position: 'absolute', top: '0', left: '0',
        width: '100%', height: '100%', zIndex: '8',
        pointerEvents: 'none', overflow: 'hidden'
    });
    root.appendChild(layer);
    let entries = [];
    let frame = null;
    let dead = false;

    function draw() {
        frame = null;
        if (dead || !root.isConnected) return;
        const width = root.clientWidth, height = root.clientHeight;
        if (width < 1 || height < 1) return;
        layer.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
        layer.setAttribute('width', String(width));
        layer.setAttribute('height', String(height));
        const fragment = document.createDocumentFragment();
        for (const marker of entries) {
            if (String(marker.source || '') !== 'AUTOTRADER_V3') continue;
            const side = String(marker.side || '').toUpperCase();
            if (side !== 'BUY' && side !== 'SELL') continue;
            const price = Number(marker.price);
            const time = Number(marker.time);
            if (!Number.isFinite(price) || !Number.isFinite(time)) continue;
            const xRaw = chart.timeScale().timeToCoordinate(time);
            const yRaw = priceSeries.priceToCoordinate(price);
            if (xRaw == null || yRaw == null) continue;
            const x = Number(xRaw), y = Number(yRaw);
            if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
            if (x < -10 || x > width + 10 || y < -15 || y > height + 15) continue;
            const up = side === 'BUY';
            const action = String(marker.action || '').toUpperCase();
            const after = marker.inventory_after;
            const afterIsZero = after != null && Number.isFinite(Number(after))
                && Math.abs(Number(after)) <= 1e-9;
            const ending = String(marker.position_direction || marker.direction || '').toUpperCase();
            const isFlatClose = action === 'CLOSE' && (ending === 'FLAT' || afterIsZero);
            // Unknown-price executions remain outlined, but never dotted:
            // 2px dashed paths fragment into stray pixels on narrow phones.
            const estimated = marker.price_verified === false;
            const sizeValue = Number(marker.size);
            const radius = Math.max(4.5, Math.min(9,
                4.5 + (Number.isFinite(sizeValue) ? sizeValue : .45) * 3
                    + (estimated ? .8 : 0)));
            // Only confirmed full closes are neutral. Partial reductions keep
            // the broker BUY/SELL triangle, regardless of the action label.
            const shape = document.createElementNS(ns, isFlatClose ? 'rect' : 'polygon');
            const color = isFlatClose ? '#94a3b8'
                : String(marker.color || (up ? '#38bdf8' : '#c084fc'));
            // Only the account inspector marks estimates explicitly false.
            // Preserve existing visual appearance for other V3 chart paths.
            if (isFlatClose) {
                const edge = Math.max(6, radius * 1.55);
                shape.setAttribute('x', (x - edge / 2).toFixed(2));
                shape.setAttribute('y', (y - edge / 2).toFixed(2));
                shape.setAttribute('width', edge.toFixed(2));
                shape.setAttribute('height', edge.toFixed(2));
            } else {
                // Keep the triangle near the actual broker execution price.
                const anchor = y + (up ? radius + 2 : -radius - 2);
                const points = up
                    ? [x,anchor-radius, x-radius,anchor+radius, x+radius,anchor+radius]
                    : [x-radius,anchor-radius, x+radius,anchor-radius, x,anchor+radius];
                shape.setAttribute('points',
                    points.reduce((a,v,i)=>a+(i%2?',':' ')+v.toFixed(2),'').trim());
            }
            shape.setAttribute('fill',estimated ? 'none' : color);
            shape.setAttribute('stroke',estimated ? color : '#111827');
            shape.setAttribute('stroke-width',estimated ? '2.6' : '1.2');
            const title = document.createElementNS(ns,'title');
            title.textContent = (isFlatClose ? 'V3 flat · posisjon lukket'
                : (up ? 'V3 kjøp' : 'V3 salg'))
                + (marker.action ? ' · ' + String(marker.action) : '')
                + (estimated ? ' · Referansepris (IKKE Saxo-fill)' :
                    (marker.price_verified === true ? ' · Saxo-verifisert fill' : ''))
                + ' · ' + price.toFixed(2);
            shape.appendChild(title);
            fragment.appendChild(shape);
        }
        layer.replaceChildren(fragment);
    }
    function schedule() {
        if (dead || frame !== null) return;
        frame = window.requestAnimationFrame(draw);
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(schedule);
    const observer = new ResizeObserver(schedule);
    observer.observe(root);
    root.addEventListener('pointerup',schedule);
    root.addEventListener('touchend',schedule,{passive:true});
    root.addEventListener('wheel',schedule,{passive:true});
    return {
        setMarkers(markers) {
            entries = Array.from(markers || [])
                .filter(m => String(m.source || '') === 'AUTOTRADER_V3');
            schedule();
        },
        destroy() {
            dead = true;
            if (frame !== null) window.cancelAnimationFrame(frame);
            observer.disconnect();
            chart.timeScale().unsubscribeVisibleLogicalRangeChange(schedule);
            root.removeEventListener('pointerup',schedule);
            root.removeEventListener('touchend',schedule);
            root.removeEventListener('wheel',schedule);
            layer.remove();
        }
    };
}

function pgV3NativeMarkers(markers) {
    // One broker event is rendered exactly once, by the triangle overlay;
    // retain all legacy/manual/AI marks unchanged on their native layers.
    return Array.from(markers || [])
        .filter(m => String(m.source || '') !== 'AUTOTRADER_V3');
}
"""

__all__ = ["V3_EXECUTION_TRIANGLE_JS"]
