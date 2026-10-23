"""One visual contract for reconciled V3 BUY/SELL markers on all V3 charts.

Native Lightweight Charts v5 supports arrowUp/arrowDown but no *triangle-only*
shape. We draw small, price/time-anchored SVG polygons over the price pane;
no DOM hit targets, no change to broker orders, candle data, or AI markers.
Use the same helper from the inspector, TradingDesk full chart and 1s updater.
"""

V3_EXECUTION_TRIANGLE_JS = r"""
function createPgV3TradeTriangleLayer(chart, priceSeries, root) {
    const ns = 'http://www.w3.org/2000/svg';
    const layer = document.createElementNS(ns, 'svg');
    layer.setAttribute('aria-label', 'V3-kjøp og salg som trekanter');
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
            const sizeValue = Number(marker.size);
            const radius = Math.max(3, Math.min(7.5,
                3.5 + (Number.isFinite(sizeValue) ? sizeValue : .45) * 3));
            // Keep the only mark near the actual broker execution price.
            const anchor = y + (up ? radius + 2 : -radius - 2);
            const shape = document.createElementNS(ns, 'polygon');
            const points = up
                ? [x,anchor-radius, x-radius,anchor+radius, x+radius,anchor+radius]
                : [x-radius,anchor-radius, x+radius,anchor-radius, x,anchor+radius];
            shape.setAttribute('points',
                points.reduce((a,v,i)=>a+(i%2?',':' ')+v.toFixed(2),'').trim());
            const color = String(marker.color || (up ? '#16a34a' : '#dc2626'));
            // Only a filled triangle, no shaft, text, square or extra symbol.
            shape.setAttribute('fill',color);
            shape.setAttribute('stroke',color);
            shape.setAttribute('stroke-width','0.5');
            const title = document.createElementNS(ns,'title');
            title.textContent = (up ? 'V3 kjøp' : 'V3 salg')
                + (marker.action ? ' · ' + String(marker.action) : '');
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
