// State helpers. Pure; node-tested. Strip owns values; this owns shape.
var SCHEMA = "openusage-omarchy.state.v1";
function parseState(raw) {
    var data;
    try {
        data = typeof raw === "string" ? JSON.parse(raw) : raw;
    } catch (_) {
        return {ok: false, error: "state is not JSON"};
    }
    if (!data || data.schema !== SCHEMA || !Array.isArray(data.cards))
        return {ok: false, error: "bad state schema"};
    return {ok: true, state: data};
}
function cardIds(state) {
    if (!state || !Array.isArray(state.cards))
        return [];
    var out = [];
    for (var i = 0; i < state.cards.length; i++) {
        if (state.cards[i] && state.cards[i].cardId)
            out.push(state.cards[i].cardId);
    }
    return out;
}
function detectedMap(state) {
    var out = {};
    if (!state || !Array.isArray(state.cards))
        return out;
    for (var i = 0; i < state.cards.length; i++) {
        var card = state.cards[i];
        if (!card || !card.family)
            continue;
        if (card.detected)
            out[card.family] = true;
        else if (!(card.family in out))
            out[card.family] = false;
    }
    return out;
}
function cardById(state, cardId) {
    if (!state || !Array.isArray(state.cards))
        return null;
    for (var i = 0; i < state.cards.length; i++) {
        if (state.cards[i] && state.cards[i].cardId === cardId)
            return state.cards[i];
    }
    return null;
}
