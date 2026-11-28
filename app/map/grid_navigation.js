function findGridRoute(graph, start, target, comfort) {
    const costs = new Map([[start, 0]]);
    const previous = new Map();
    const queue = [[0, start]];
    while (queue.length) {
        const [cost, gridId] = queue.shift();
        if (cost !== costs.get(gridId)) continue;
        if (gridId === target) {
            const path = [gridId];
            let distance = 0;
            for (let edge = previous.get(gridId); edge; edge = previous.get(edge.gridId)) {
                path.push(edge.gridId);
                distance += edge.distance;
            }
            return {path:path.reverse(), distance};
        }
        for (const edge of graph.get(gridId)) {
            const next = cost + edge.distance + (comfort ? edge.penalty : 0);
            if (next >= (costs.get(edge.gridId) ?? Infinity)) continue;
            costs.set(edge.gridId, next);
            previous.set(edge.gridId, {gridId, distance:edge.distance});
            let index = queue.length;
            while (index > 0 && queue[index - 1][0] > next) index--;
            queue.splice(index, 0, [next, edge.gridId]);
        }
    }
    return null;
}

function distanceToGrid(point, corners) {
    let nearest = Infinity;
    let left = false;
    let right = false;
    for (let index = 0; index < corners.length; index++) {
        const from = corners[index];
        const to = corners[(index + 1) % corners.length];
        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const x = point.x - from.x;
        const y = point.y - from.y;
        const side = dx * y - dy * x;
        left ||= side > 0;
        right ||= side < 0;
        const fraction = Math.max(0, Math.min(1, (x * dx + y * dy) / (dx * dx + dy * dy)));
        nearest = Math.min(nearest, Math.hypot(x - fraction * dx, y - fraction * dy));
    }
    return left && right ? nearest : 0;
}

function setupEntranceNavigation(map, data) {
    const entranceLayer = L.layerGroup().addTo(map);
    const startLayer = L.layerGroup().addTo(map);
    const routeLayer = L.layerGroup().addTo(map);
    const routePane = map.createPane('grid-route');
    routePane.style.zIndex = 625;
    routePane.style.pointerEvents = 'none';
    const routeStyle = {pane:'grid-route', interactive:false};
    const menu = document.getElementById('entrance-select');
    const toggle = document.getElementById('entrances');
    const recommended = document.getElementById('recommended-only');
    const startButton = document.getElementById('map-origin');
    const gpsButton = document.getElementById('gps-origin');
    const mode = document.getElementById('route-mode');
    const result = document.getElementById('route-result');
    const cellById = new Map(data.cells.map(cell => [cell.grid_id, cell]));
    const observed = data.cells.filter(cell => cell.observation_count > 0);
    const graph = new Map(observed.map(cell => [cell.grid_id, []]));
    const project = latlng => map.options.crs.project(L.latLng(latlng));
    const polygons = observed.map(cell => [cell.grid_id, cell.corners.map(project)]);
    const maxStartOffset = 25;
    let start = null;
    let startCell = null;
    let pickingStart = false;
    let gpsRequest = 0;

    for (const [a, b, distance, penalty] of data.grid_edges) {
        graph.get(a).push({gridId:b, distance, penalty});
        graph.get(b).push({gridId:a, distance, penalty});
    }

    const nameOf = ({properties:p}) => [p.building_name, p.entrance_name].filter(Boolean).join(' · ') || 'Unnamed entrance';
    const formatDistance = distance => distance < 1 ? distance.toFixed(1) + ' m' : Math.round(distance) + ' m';
    const featureValue = (state, amount, unit) => {
        if (state === 'no') return 'none';
        if (state !== 'yes') return 'unknown';
        return amount == null ? 'present' : amount + ' ' + unit;
    };
    const entries = data.entrances.map((entry, index) => {
        const p = entry.properties;
        const title = nameOf(entry);
        const latlng = L.latLng(entry.lat, entry.lon);
        const place = p.kind === 'place';
        const accessible = p.wheelchair?.recommended;
        const color = place ? 'place' : accessible === true ? '' : 'restricted';
        const marker = L.marker(latlng, {
            title,
            alt:title,
            bubblingMouseEvents:false,
            zIndexOffset:500,
            icon:L.divIcon({className:'entrance-pin ' + color, html:place ? '•' : '↪', iconSize:[24,24], iconAnchor:[12,12]}),
        });
        const popup = document.createElement('div');
        const heading = document.createElement('strong');
        heading.textContent = title;
        popup.append(heading);
        const details = document.createElement('p');
        const access = accessible === true ? 'Wheelchair-recommended entrance' : accessible === false ? 'Wheelchair access difficult' : 'Wheelchair access unknown';
        const features = 'Ramp ' + featureValue(p.ramp) + ' · Steps ' + featureValue(p.stairs?.state, p.stairs?.amount, 'steps') + ' · Threshold ' + featureValue(p.threshold_cm?.state, p.threshold_cm?.amount, 'cm');
        details.textContent = place ? 'Registered place' : [access, features, ...(p.wheelchair?.reasons || []), p.opening_hours, p.note].filter(Boolean).join('\n');
        details.style.whiteSpace = 'pre-line';
        popup.append(details);
        if (!place) {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = 'Route to this entrance’s grid';
            button.onclick = () => chooseEntrance(index);
            popup.append(button);
        }
        if (typeof p.photo_url === 'string' && /^https:\/\//i.test(p.photo_url)) {
            const photo = document.createElement('a');
            photo.href = p.photo_url;
            photo.target = '_blank';
            photo.rel = 'noopener noreferrer';
            photo.textContent = 'Photo';
            const line = document.createElement('p');
            line.append(photo);
            popup.append(line);
        }
        marker.bindPopup(popup);
        marker.on('click', () => {
            if (pickingStart) setStart(latlng);
            else if (!place) chooseEntrance(index, false);
        });
        return {...entry, index, title, marker, latlng, place, accessible};
    });

    function updateEntrances() {
        entranceLayer.clearLayers();
        const selected = menu.value;
        menu.length = 1;
        const allowed = entries.filter(entry => !recommended.checked || entry.accessible === true && !entry.place);
        for (const entry of allowed) entry.marker.addTo(entranceLayer);
        for (const entry of allowed.filter(entry => !entry.place).sort((a,b) => a.title.localeCompare(b.title, 'ko'))) {
            menu.add(new Option(entry.title, entry.index));
        }
        menu.value = [...menu.options].some(option => option.value === selected) ? selected : '';
        drawRoute();
    }

    function chooseEntrance(index, focus = true) {
        menu.value = index;
        const entry = entries[index];
        if (focus && !entry.target) map.panTo(entry.latlng);
        drawRoute(focus);
    }

    function setPickingStart(enabled) {
        pickingStart = enabled;
        startButton.setAttribute('aria-pressed', String(enabled));
        map.getContainer().classList.toggle('picking-start', enabled);
    }

    function setStart(latlng) {
        gpsRequest++;
        setPickingStart(false);
        map.closePopup();
        startLayer.clearLayers();
        start = latlng;
        L.circleMarker(start, {...routeStyle, radius:7, color:'#fff', fillColor:'#075985', fillOpacity:1}).addTo(startLayer);
        const position = project(start);
        // Web Mercator의 위치별 축척을 보정해 시작점과 격자 경계의 거리를 잰다.
        const scale = Math.cos(start.lat * Math.PI / 180);
        startCell = null;
        let nearest = Infinity;
        for (const [gridId, corners] of polygons) {
            const distance = distanceToGrid(position, corners) * scale;
            if (distance >= nearest) continue;
            nearest = distance;
            startCell = {gridId, distance};
        }
        if (nearest > maxStartOffset) startCell = null;
        drawRoute(true);
    }

    function highlightEntrance() {
        for (const entry of entries) {
            entry.marker.getElement()?.classList.toggle('selected', menu.value === String(entry.index));
        }
    }

    function drawRoute(fit = false) {
        routeLayer.clearLayers();
        highlightEntrance();
        if (menu.value === '') {
            result.textContent = start ? 'Start set. Choose an entrance.' : 'Choose an entrance and a starting point.';
            return;
        }
        const entry = entries[Number(menu.value)];
        const target = entry.target;
        if (!target) {
            result.textContent = 'No observed grid is available for this entrance.';
            return;
        }
        const cell = cellById.get(target.grid_id);
        const route = startCell && findGridRoute(graph, startCell.gridId, target.grid_id, mode.value === 'comfort');
        L.polygon(cell.corners, {...routeStyle, color:'#7c3aed', weight:4, fillOpacity:0.08}).addTo(routeLayer);
        let message = 'G' + target.grid_id + ' · ' + cell.observation_count + ' observations · ';
        message += target.in_cell ? 'Entrance is inside this grid.' : 'Nearest observed grid is ' + formatDistance(target.distance_m) + ' from the entrance.';
        if (entry.accessible === false) message += '\nWheelchair access at this entrance is difficult.';
        const bounds = L.latLngBounds(cell.corners).extend(entry.latlng);
        if (route) {
            const path = route.path.map(gridId => cellById.get(gridId).center);
            const destination = path[path.length - 1];
            L.polygon(cellById.get(startCell.gridId).corners, {
                ...routeStyle, color:'#075985', weight:2, dashArray:'4 4', fill:false,
            }).addTo(routeLayer);
            L.polyline(path, {...routeStyle, color:'#fff', weight:8}).addTo(routeLayer);
            L.polyline(path, {...routeStyle, color:'#075985', weight:5}).addTo(routeLayer);
            L.circleMarker(destination, {...routeStyle, radius:6, color:'#fff', fillColor:'#7c3aed', fillOpacity:1}).addTo(routeLayer);
            bounds.extend(L.latLngBounds(path)).extend(start);
            message += '\n' + (mode.value === 'comfort' ? 'Comfort first' : 'Shortest') + ' · ' + formatDistance(route.distance) + ' between grid centers.';
            message += '\nG' + startCell.gridId + ' → G' + target.grid_id + ' · ' + route.path.length + ' grid ' + (route.path.length === 1 ? 'cell.' : 'cells.');
            if (startCell.distance > 0) message += '\nThe start grid is ' + formatDistance(startCell.distance) + ' from your pin.';
            message += '\nGrid-based estimate. Check walkability on site.';
        } else if (!start) {
            message += '\nSet a start on the map or use your location.';
        } else if (startCell === null) {
            message += '\nNo observed grid within ' + maxStartOffset + ' m of your start.';
        } else {
            message += '\nNo connected path through observed grids from G' + startCell.gridId + '.';
        }
        result.textContent = message;
        if (fit) map.fitBounds(bounds.pad(0.16), {maxZoom:19});
    }

    document.getElementById('navigation').hidden = false;
    document.getElementById('entrance-toggle').hidden = false;
    toggle.onchange = () => {
        if (toggle.checked) entranceLayer.addTo(map);
        else entranceLayer.remove();
        highlightEntrance();
    };
    recommended.onchange = updateEntrances;
    menu.onchange = () => menu.value === '' ? drawRoute() : chooseEntrance(Number(menu.value));
    mode.onchange = () => drawRoute();
    startButton.onclick = () => {
        gpsRequest++;
        setPickingStart(!pickingStart);
        if (pickingStart) result.textContent = 'Click the map to set your start.';
        else drawRoute();
    };
    gpsButton.onclick = () => {
        if (!navigator.geolocation) {
            result.textContent = 'Location unavailable. Set the start on the map.';
            return;
        }
        setPickingStart(false);
        const request = ++gpsRequest;
        result.textContent = 'Finding your location…';
        navigator.geolocation.getCurrentPosition(position => {
            if (request !== gpsRequest) return;
            setStart(L.latLng(position.coords.latitude, position.coords.longitude));
        }, () => {
            if (request === gpsRequest) result.textContent = 'Location unavailable. Set the start on the map.';
        }, {enableHighAccuracy:true, timeout:10000, maximumAge:0});
    };
    map.on('click', event => { if (pickingStart) setStart(event.latlng); });
    setPickingStart(false);
    updateEntrances();
}
