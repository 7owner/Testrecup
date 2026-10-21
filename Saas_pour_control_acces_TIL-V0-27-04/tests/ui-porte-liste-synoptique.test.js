'use strict';

// Logiciel TIL V2, interface de app/index.html dans Chromium (Playwright) :
//  - editeur de porte : P1 a P6, arbre des portes : P7 ;
//  - liste des portes : R1 a R4 ;
//  - synoptique : Y1 a Y5 ;
//  - onglet « Generation du code » : G1 a G4 ;
//  - cache du service worker : W1.
// Aucune impression reelle, aucun export Excel.
const fs = require('fs');
const path = require('path');
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const { getRacineApp } = require('./helpers/racine');
const fx = require('./helpers/fixtures');
const { demarrerApp, preparerPage } = require('./helpers/page');

const TIL = chargerGenerator();
const OPTIONS = { timeout: 30000 };

let app;
before(async () => { app = await demarrerApp(); });
after(async () => { if (app) await app.fermer(); });

async function avecPage(tillys, scenario) {
  const session = await preparerPage(app, tillys);
  try {
    return await scenario(session);
  } finally {
    await session.context.close();
  }
}

// Interrupteurs de l'editeur ouvert : libelle (strong) et presence d'une aide (small).
function lireInterrupteurs() {
  return [...document.querySelectorAll('#door-edit-body .portes-switch-copy')].map(copie => ({
    libelle: (copie.querySelector('strong') || {}).textContent?.trim() || '',
    aide: !!copie.querySelector('small'),
  }));
}

// ── Editeur de porte ─────────────────────────────────────────────────────

test('P1 editeur : le lecteur d\'entree « — » est conserve (affichage, enregistrement, reouverture)', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      const valeurSelect = () => {
        const champ = [...document.querySelectorAll('#door-edit-body .portes-editor-field')]
          .find(f => (f.querySelector('span') || {}).textContent?.trim() === 'Lecteur entrée');
        return champ ? champ.querySelector('select').value : null;
      };
      ouvrirPorteEditor(3);
      updatePorteDraft('lecteurEntree', '');
      const brouillon = PORTES_UI.editingDraft.lecteurEntree;
      const affiche = valeurSelect();
      validerPorteEditor();
      const enregistre = getTillysActif().portes[2].lecteurEntree;
      fermerPorteEditor();
      ouvrirPorteEditor(3);
      const rouvert = valeurSelect();
      fermerPorteEditor();
      return { brouillon, affiche, enregistre, rouvert };
    });
    assert.equal(etat.brouillon, '', 'precondition : le brouillon recoit le lecteur vide');
    assert.equal(etat.affiche, '', 'le select affiche « — » et ne retombe pas sur LB');
    assert.equal(etat.enregistre, '', 'la porte enregistree n\'a pas de lecteur d\'entree');
    assert.equal(etat.rouvert, '', 'a la reouverture, le select reste sur « — »');
  });
});

test('P2 editeur, onglet Tillys / Modules : libelle « ML associé »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const libelles = await page.evaluate(() => {
      ouvrirPorteEditor(1, 'hardware');
      const l = [...document.querySelectorAll('#door-edit-body .portes-editor-field > span')].map(s => s.textContent.trim());
      fermerPorteEditor();
      return l;
    });
    assert.ok(libelles.includes('Tillys associe'), `precondition : onglet materiel rendu : ${libelles.join(' | ')}`);
    assert.ok(libelles.includes('ML associé'), `libelle « ML associé » absent : ${libelles.join(' | ')}`);
    assert.ok(!libelles.includes('MLP2 associe'), 'ancien libelle « MLP2 associe » encore present');
  });
});

test('P3 select ML : 8 relais par MLR8 du bus (« MLR8 A9 – Rn »), relais pris par une autre porte masques', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    const lire = num => page.evaluate(n => {
      ouvrirPorteEditor(n, 'hardware');
      const select = [...document.querySelectorAll('#door-edit-body select')]
        .find(s => [...s.options].some(o => o.value.startsWith('module:')));
      const options = select ? [...select.options].map(o => ({ valeur: o.value, libelle: o.textContent.trim(), choisi: o.selected })) : null;
      fermerPorteEditor();
      return options;
    }, num);

    const porte3 = await lire(3);
    assert.ok(porte3, 'precondition : select ML de la porte 3 rendu');
    const relais3 = porte3.filter(o => o.valeur.startsWith('relais:'));
    assert.deepEqual(relais3.map(o => o.valeur), [1, 2, 4, 5, 6, 7, 8].map(n => `relais:MR9:${n}`),
      'porte 3 : relais du MLR8 A9, sans R3 pris par la porte 4');
    assert.deepEqual(relais3.map(o => o.libelle), [1, 2, 4, 5, 6, 7, 8].map(n => `MLR8 A9 – R${n}`));
    assert.ok(porte3.some(o => o.valeur === 'module:MA1'), 'les MLP2 restent proposes');

    const porte4 = await lire(4);
    const choisi = (porte4 || []).find(o => o.choisi);
    assert.equal(choisi && choisi.valeur, 'relais:MR9:3', 'porte 4 : son relais R3 est propose et selectionne');
  });
});

test('P4 editeur : libelles « Barre anti panique », « Cmd Hypervision », « POTL »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const libelles = await page.evaluate(lire => {
      ouvrirPorteEditor(1);
      const l = (new Function(`return (${lire})()`))().map(i => i.libelle);
      fermerPorteEditor();
      return l;
    }, lireInterrupteurs.toString());
    assert.ok(libelles.includes('BP sortie'), `precondition : interrupteurs rendus : ${libelles.join(' | ')}`);
    ['Barre anti panique', 'Cmd Hypervision', 'POTL', 'Effraction', 'Mode visiteur', 'Déclencheur manuel']
      .forEach(l => assert.ok(libelles.includes(l), `libelle « ${l} » absent : ${libelles.join(' | ')}`));
    ['BAP', 'Cmd Hyper', 'Timer / POTL'].forEach(l => assert.ok(!libelles.includes(l), `ancien libelle « ${l} » present`));
  });
});

test('P5 editeur : pas d\'aide sous BP sortie, Declencheur manuel, Barre anti panique, Mode visiteur ; aide conservee ailleurs', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const interrupteurs = await page.evaluate(lire => {
      ouvrirPorteEditor(1);
      const l = (new Function(`return (${lire})()`))();
      fermerPorteEditor();
      return l;
    }, lireInterrupteurs.toString());
    const aide = libelle => {
      const i = interrupteurs.find(x => x.libelle === libelle);
      assert.ok(i, `interrupteur « ${libelle} » absent : ${interrupteurs.map(x => x.libelle).join(' | ')}`);
      return i.aide;
    };
    ['BP sortie', 'Déclencheur manuel', 'Barre anti panique', 'Mode visiteur']
      .forEach(l => assert.equal(aide(l), false, `« ${l} » : aide <small> a retirer`));
    ['Cmd Hypervision', 'POTL', 'Effraction'].forEach(l => assert.equal(aide(l), true, `« ${l} » : aide <small> a garder`));
  });
});

test('P6 editeur, section Câblage : plus de ligne « défaut carnet »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const texte = await page.evaluate(() => {
      ouvrirPorteEditor(1);
      const section = document.querySelector('#door-edit-body .portes-cable-section');
      const t = section ? section.textContent.replace(/\s+/g, ' ') : null;
      fermerPorteEditor();
      return t;
    });
    assert.ok(texte, 'precondition : section Câblage rendue');
    assert.ok(!/défaut carnet/i.test(texte), `ligne « défaut carnet » encore presente : ${texte}`);
  });
});

// L'onglet Portes est retire de la navigation (showTab le renvoie vers la liste
// des portes) mais renderTableauPortes() reste appele par l'editeur : on rend
// l'arbre des portes directement et on lit ses etiquettes.
test('P7 arbre des portes (renderTableauPortes) : une porte sans lecteur d\'entree n\'affiche pas « LB »', OPTIONS, async () => {
  await avecPage(fx.fixtureSansLecteur(TIL), async ({ page }) => {
    const etiquettes = await page.evaluate(() => {
      renderTableauPortes();
      const lire = n => {
        const feuille = [...document.querySelectorAll('#portes-tree-root article.porte-tree-leaf')]
          .find(a => [...a.querySelectorAll('button')].some(b => (b.getAttribute('onclick') || '').replace(/\s+/g, '') === `ouvrirPorteEditor(${n})`));
        return feuille ? [...feuille.querySelectorAll('.porte-app-tag')].map(s => s.textContent.trim()) : null;
      };
      return { 1: lire(1), 3: lire(3), lecteur3: getTillysActif().portes[2].lecteurEntree };
    });
    assert.equal(etiquettes.lecteur3, '', 'precondition : porte 3 sans lecteur d\'entree');
    assert.ok(etiquettes[1] && etiquettes[3], 'precondition : portes 1 et 3 rendues dans l\'arbre des portes');
    assert.ok(etiquettes[1].includes('LB'), `precondition : la porte 1 affiche son lecteur LB : ${etiquettes[1].join(' | ')}`);
    assert.ok(!etiquettes[3].includes('LB'), `porte 3 sans lecteur affichee « LB » : ${etiquettes[3].join(' | ')}`);
  });
});

// ── Liste des portes ─────────────────────────────────────────────────────

// Badges standard de la ligne d'une porte dans la liste du projet.
async function badgesListe(page, nums) {
  return page.evaluate(numeros => {
    showTab('tab-liste-portes');
    const resultat = {};
    numeros.forEach(n => {
      const article = [...document.querySelectorAll('#liste-portes-container article.project-door-soft-row')]
        .find(a => (a.getAttribute('onclick') || '').replace(/\s+/g, '') === `ouvrirPorteDepuisProjet(0,${n})`);
      resultat[n] = article ? [...article.querySelectorAll('.badge.badge-standard')].map(b => b.textContent.trim()) : null;
    });
    return resultat;
  }, nums);
}

test('R1 liste des portes : badges Mode Visiteur, Cmd Hyperviseur, POTL, Effraction comme BP / DM', OPTIONS, async () => {
  const t = fx.fixtureBase(TIL);
  t.portes[1].mode = 'visiteur';
  await avecPage(t, async ({ page }) => {
    const badges = await badgesListe(page, [1, 2]);
    assert.ok(badges[1] && badges[2], 'precondition : lignes des portes 1 et 2 rendues');
    assert.ok(badges[1].includes('BP') && badges[1].includes('DM'), `precondition : badges BP / DM de la porte 1 : ${badges[1].join(' | ')}`);
    ['Cmd Hyperviseur', 'POTL', 'Effraction'].forEach(b => {
      assert.ok(badges[1].includes(b), `porte 1 : badge « ${b} » absent : ${badges[1].join(' | ')}`);
      assert.ok(badges[2].includes(b), `porte 2 : badge « ${b} » absent : ${badges[2].join(' | ')}`);
    });
    assert.ok(badges[2].includes('Mode Visiteur'), `porte 2 visiteur : badge « Mode Visiteur » absent : ${badges[2].join(' | ')}`);
    assert.ok(!badges[1].includes('Mode Visiteur'), 'porte 1 standard : pas de badge « Mode Visiteur »');
  });
});

test('R2 liste des portes : badges absents quand la fonction est coupee (POTL coupe par Timer ou POTL)', OPTIONS, async () => {
  await avecPage(fx.fixtureOptionsOff(TIL), async ({ page }) => {
    const badges = await badgesListe(page, [1, 3]);
    assert.ok(badges[1] && badges[3], 'precondition : lignes des portes 1 et 3 rendues');
    ['Cmd Hyperviseur', 'POTL', 'Effraction', 'Mode Visiteur'].forEach(b => {
      assert.ok(!badges[1].includes(b), `porte 1 : badge « ${b} » alors que la fonction est coupee`);
    });
    assert.ok(!badges[3].includes('POTL'), 'porte 3 : POTL coupe, pas de badge « POTL »');
    assert.ok(badges[3].includes('Cmd Hyperviseur') && badges[3].includes('Effraction'),
      `porte 3 : badges Cmd Hyperviseur et Effraction attendus : ${badges[3].join(' | ')}`);
  });
});

test('R3 liste des portes : actions en dernier, hors designation, Dupliquer au-dessus de Supprimer, a droite', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const mesure = await page.evaluate(() => {
      showTab('tab-liste-portes');
      const article = document.querySelector('#liste-portes-container article.project-door-soft-row');
      if (!article) return null;
      const actions = article.querySelector('.project-door-row-actions');
      const boutons = actions ? [...actions.querySelectorAll('button')] : [];
      const rect = el => el.getBoundingClientRect();
      const dupliquer = boutons.find(b => b.textContent.trim() === 'Dupliquer');
      const supprimer = boutons.find(b => b.textContent.trim() === 'Supprimer');
      return {
        actions: !!actions,
        dernier: article.lastElementChild === actions,
        dansDesignation: !!(actions && actions.closest('.is-designation')),
        dupliquer: dupliquer ? rect(dupliquer).toJSON() : null,
        supprimer: supprimer ? rect(supprimer).toJSON() : null,
        article: rect(article).toJSON(),
        bloc: actions ? rect(actions).toJSON() : null,
      };
    });
    assert.ok(mesure && mesure.actions, 'precondition : actions de la ligne rendues');
    assert.ok(mesure.dupliquer && mesure.supprimer, 'precondition : boutons Dupliquer et Supprimer');
    assert.equal(mesure.dansDesignation, false, 'les actions ne sont plus dans la cellule de designation');
    assert.equal(mesure.dernier, true, 'les actions sont le dernier enfant de la ligne');
    assert.ok(mesure.dupliquer.bottom <= mesure.supprimer.top + 1, 'Dupliquer au-dessus de Supprimer');
    assert.ok(mesure.bloc.left >= mesure.article.left + mesure.article.width / 2, 'actions dans la moitie droite de la ligne');
  });
});

test('R4 liste des portes : le bloc de gauche (site, designation, reperage) est centre verticalement', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const ecarts = await page.evaluate(() => {
      showTab('tab-liste-portes');
      return [...document.querySelectorAll('#liste-portes-container article.project-door-soft-row')].map(article => {
        const a = article.getBoundingClientRect();
        // Bloc de texte de gauche : textes de la cellule de designation, sans les actions.
        const textes = [...article.querySelector('.is-designation').children]
          .filter(el => !el.classList.contains('project-door-row-actions'))
          .map(el => el.getBoundingClientRect())
          .filter(r => r.height > 0);
        const haut = Math.min(...textes.map(r => r.top));
        const bas = Math.max(...textes.map(r => r.bottom));
        return { ecart: Math.abs((haut + bas) / 2 - (a.top + a.bottom) / 2), textes: textes.length };
      });
    });
    assert.ok(ecarts.length >= 4, 'precondition : lignes de la liste rendues');
    ecarts.forEach((e, i) => {
      assert.ok(e.textes >= 2, `ligne ${i + 1} : precondition, textes de la designation rendus`);
      assert.ok(e.ecart <= 3, `ligne ${i + 1} : bloc de gauche decentre de ${e.ecart.toFixed(1)} px`);
    });
  });
});

// ── Synoptique ───────────────────────────────────────────────────────────

async function rendreSynoptique(page) {
  await page.evaluate(() => { showTab('tab-synoptic'); renderSynoptique(); });
}

test('Y1 synoptique : plus aucune etiquette « … off » ; APERIO reste affiche', OPTIONS, async () => {
  await avecPage(fx.fixtureOptionsOff(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const tags = await page.$$eval('#synoptic-root .synoptic-door-node .synoptic-mini-tag', els => els.map(e => e.textContent.trim()));
    const portes = await page.locator('#synoptic-root .synoptic-door-node').count();
    assert.ok(portes >= 3, 'precondition : portes rendues dans le synoptique');
    assert.deepEqual(tags.filter(t => /\boff\b/i.test(t)), [], 'etiquettes « off » encore affichees');
  });
  await avecPage(fx.fixtureAperio(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const tags = await page.$$eval('#synoptic-root [data-drag-porte-num="6"] .synoptic-mini-tag', els => els.map(e => e.textContent.trim()));
    assert.ok(tags.includes('APERIO'), `porte APERIO 6 : etiquette APERIO absente : ${tags.join(' | ')}`);
  });
});

test('Y2 synoptique : la recherche de porte n\'offre plus les portes deja sur un MLP2 ou un MLR8', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const { valeurs, attendus } = await page.evaluate(() => {
      const tri = n => TIL.composerTriNumPorte(APP.tillys[0].portes[n - 1], n);
      return {
        valeurs: [...document.querySelectorAll('#synoptic-door-search-list option')].map(o => o.value),
        attendus: { libres: [tri(10)], pris: [1, 2, 3, 4].map(tri) },
      };
    });
    attendus.libres.forEach(v => assert.ok(valeurs.includes(v), `porte libre ${v} absente de la liste : ${valeurs.join(' | ')}`));
    attendus.pris.forEach(v => assert.ok(!valeurs.includes(v), `porte ${v} deja raccordee encore proposee`));
  });
});

// Texte, meta, champ et bouton d'ajout de la carte d'un module.
async function carteModule(page, type) {
  return page.evaluate(t => {
    const carte = document.querySelector(`#synoptic-root .synoptic-module-card[data-module-type="${t}"]`);
    if (!carte) return null;
    return {
      texte: carte.textContent.replace(/\s+/g, ' ').trim(),
      meta: carte.querySelectorAll('.synoptic-module-meta').length,
      champ: carte.querySelectorAll('input[list="synoptic-door-search-list"]').length,
      ajouter: [...carte.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Ajouter porte').map(b => !b.disabled),
      voirCablage: [...carte.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Voir le câblage').length,
    };
  }, type);
}

test('Y3 synoptique, carte MLIO : ni meta, ni ajout de porte, ni compteur, ni « Voir le câblage »', OPTIONS, async () => {
  await avecPage(fx.fixtureModulesTerrain(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const carte = await carteModule(page, 'MLIO');
    assert.ok(carte, 'precondition : carte MLIO rendue');
    assert.match(carte.texte, /MLIO A10/, 'precondition : nom du module affiche');
    assert.equal(carte.meta, 0, 'pas de ligne meta (type · adresse · protocole)');
    assert.equal(carte.champ, 0, 'pas de champ de recherche de porte');
    assert.deepEqual(carte.ajouter, [], 'pas de bouton « Ajouter porte »');
    assert.equal(carte.voirCablage, 0, 'pas de bouton « Voir le câblage »');
    ['Aucune porte raccord', '/16 porte(s)', '16 entrees terrain'].forEach(t => assert.ok(!carte.texte.includes(t), `« ${t} » encore affiche`));
  });
});

test('Y4 synoptique, carte MLR8 : ni meta, ni compteur, ni « Voir le câblage », mais ajout de porte', OPTIONS, async () => {
  await avecPage(fx.fixtureModulesTerrain(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const carte = await carteModule(page, 'MLR8');
    assert.ok(carte, 'precondition : carte MLR8 rendue');
    assert.match(carte.texte, /MLR8 A9/, 'precondition : nom du module affiche');
    assert.equal(carte.meta, 0, 'pas de ligne meta (type · adresse · protocole)');
    assert.equal(carte.voirCablage, 0, 'pas de bouton « Voir le câblage »');
    ['/8 porte(s)', '8 relais terrain'].forEach(t => assert.ok(!carte.texte.includes(t), `« ${t} » encore affiche`));
    assert.deepEqual(carte.ajouter, [true], 'bouton « Ajouter porte » present et actif');
    assert.equal(carte.champ, 1, 'champ de recherche de porte present');
  });
});

test('Y5 synoptique : la porte 4 sur le MLR8 A9 affiche son relais « R3 »', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ page }) => {
    await rendreSynoptique(page);
    const metas = await page.$$eval('#synoptic-root .synoptic-module-card[data-module-type="MLR8"] [data-drag-porte-num="4"] .synoptic-door-meta',
      els => els.map(e => e.textContent.trim()));
    assert.deepEqual(metas, ['R3']);
  });
});

// ── Onglet Generation du code ────────────────────────────────────────────

test('G1 onglet code : ni « Sélectionnez un Tillys », ni « Générer tout », ni carte d\'explication', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const etat = await page.evaluate(() => {
      showTab('tab-code');
      const code = document.getElementById('tab-code');
      const adresses = document.getElementById('tab-adresses');
      return {
        texte: code.textContent.replace(/\s+/g, ' '),
        explication: code.querySelectorAll('.code-explain-card').length,
        boutonsTout: [...code.querySelectorAll('button')].filter(b => /Générer tout/.test(b.textContent)).length,
        placeholders: [...code.querySelectorAll('textarea')].map(t => t.getAttribute('placeholder') || ''),
        adresses: adresses.textContent.includes('Sélectionnez un Tillys ci-dessus'),
      };
    });
    assert.ok(!etat.texte.includes('Sélectionnez un Tillys ci-dessus'), 'consigne « Sélectionnez un Tillys » encore dans l\'onglet code');
    assert.equal(etat.boutonsTout, 0, 'bouton « Générer tout » encore present');
    assert.ok(!/Générer tout/.test(etat.texte + etat.placeholders.join(' ')), 'texte « Générer tout » encore present');
    assert.equal(etat.explication, 0, 'carte « Explication du code » encore presente');
    assert.equal(etat.adresses, true, 'non-regression : la consigne reste dans l\'onglet adresses');
  });
});

test('G2 onglet code : une seule barre (titre, onglets, commande logique, MIL_DOOR, Régénérer le code)', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const barre = await page.evaluate(() => {
      showTab('tab-code');
      const code = document.getElementById('tab-code');
      const titre = [...code.querySelectorAll('h2')].find(h => h.textContent.trim() === 'Génération du Code TIL');
      const regenerer = [...code.querySelectorAll('button')].find(b => b.textContent.trim() === 'Régénérer le code');
      const membres = [titre, code.querySelector('.code-tabs'), document.getElementById('opt-locked-polarity'),
        document.getElementById('code-opt-mildoor'), regenerer];
      if (membres.some(m => !m)) return { manquants: membres.map(m => !!m) };
      let ancetre = titre.parentElement;
      while (ancetre && !membres.every(m => ancetre.contains(m))) ancetre = ancetre.parentElement;
      return {
        estOnglet: ancetre === code,
        texte: ancetre ? ancetre.textContent.replace(/\s+/g, ' ') : '',
      };
    });
    assert.ok(!barre.manquants, `elements absents (titre, onglets, polarite, MIL_DOOR, Régénérer) : ${JSON.stringify(barre.manquants)}`);
    assert.equal(barre.estOnglet, false, 'titre, onglets et options doivent partager une meme barre, pas seulement l\'onglet');
    assert.ok(barre.texte.includes('Commande logique'), 'libelle « Commande logique » dans la barre');
    assert.ok(barre.texte.includes('Activation MIL_DOOR pour MILESTONE'), 'libelle « Activation MIL_DOOR pour MILESTONE » dans la barre');
  });
});

test('G3 (non-regression) onglet code : le code est genere a l\'ouverture', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const sorties = await page.evaluate(() => {
      showTab('tab-code');
      return ['microcode-output', 'srv-utl-output', 'utl-srv-output'].map(id => document.getElementById(id).value);
    });
    assert.ok(sorties[0].includes('EV(M1==1)'), 'microcode genere a l\'ouverture');
    assert.ok(sorties[1].includes('A_N0_1.cmd=M1'), 'serveur -> UTL genere a l\'ouverture');
    assert.ok(sorties[2].includes('A_N0_1.locked=DA0102'), 'UTL -> serveur genere a l\'ouverture');
  });
});

test('G4 (non-regression) onglet code : polarite inversee et MIL_DOOR depuis la barre, puis « Régénérer le code »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    await page.evaluate(() => showTab('tab-code'));
    await page.selectOption('#opt-locked-polarity', 'inverted');
    // Interrupteur masque derriere sa piste : clic sur la case elle-meme (declenche change).
    await page.evaluate(() => document.getElementById('code-opt-mildoor').click());
    assert.equal(await page.locator('#code-opt-mildoor').isChecked(), true, 'precondition : MIL_DOOR coche');
    await page.locator('#tab-code button', { hasText: 'Régénérer le code' }).click();
    const sorties = await page.evaluate(() => ({
      microcode: document.getElementById('microcode-output').value,
      srv: document.getElementById('srv-utl-output').value,
    }));
    assert.ok(sorties.microcode.includes('EV(M1==0)'), 'polarite inversee : EV(M1==0)');
    assert.ok(sorties.srv.includes('MIL_DOOR_A_N0_1.cmd=M1'), 'Milestone : prefixe MIL_DOOR_');
  });
});

// ── Service worker ───────────────────────────────────────────────────────

test('W1 cache du service worker renomme (fichiers statiques modifies)', () => {
  const source = fs.readFileSync(path.join(getRacineApp(), 'app', 'sw.js'), 'utf8');
  const m = source.match(/const\s+CACHE_NAME\s*=\s*['"]([^'"]+)['"]/);
  assert.ok(m, 'CACHE_NAME introuvable dans app/sw.js');
  assert.notEqual(m[1], 'til-access-v20', 'CACHE_NAME doit changer pour invalider l\'ancien cache');
});
