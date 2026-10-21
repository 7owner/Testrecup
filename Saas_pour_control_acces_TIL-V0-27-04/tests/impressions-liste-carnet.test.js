'use strict';

// Logiciel TIL V2 : documents imprimables de l'onglet « Liste des portes »,
// d'apres les modeles LISTE DE PORTE GENERAL (A4 portrait) et CARNET DE CABLE
// GENERAL (A4 paysage). Liste de porte : L1 a L7 ; carnet de cable : K1 a K8.
// Aucune impression reelle (window.print neutralise), aucun export Excel :
// l'export du carnet est remplace par un compteur dans la page.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');
const { demarrerApp, preparerPage, capturerPopup, largeurImage } = require('./helpers/page');

const TIL = chargerGenerator();
const OPTIONS = { timeout: 30000 };
const LOGO = 'img[src*="logo-fauche-digital.png"]';
const PROJET = { nom: 'LE PHOCEA', batiment: 'TERTIAIRE', ref: 'P-2026-017' };
const BARRE = '#tab-liste-portes .btn-group button';

let app;
before(async () => { app = await demarrerApp(); });
after(async () => { if (app) await app.fermer(); });

// Contexte neuf avec la fixture et les informations du projet.
async function avecPage(tillys, scenario, projet = PROJET) {
  const session = await preparerPage(app, tillys);
  try {
    await session.page.evaluate(p => { Object.assign(APP.projet, p); }, projet);
    return await scenario(session);
  } finally {
    await session.context.close();
  }
}

// Clique le bouton de la barre de la liste des portes dont le libelle est
// exactement `libelle` et renvoie la fenetre ouverte. Les exports Excel sont
// neutralises avant le clic : aucun fichier ne doit etre genere par le test.
async function cliquerBarre(context, page, libelle) {
  await page.evaluate(() => {
    window.__exportsExcel = 0;
    window.exporterCarnetCableExcel = () => { window.__exportsExcel += 1; };
    window.exporterListePortesExcel = () => { window.__exportsExcel += 1; };
    showTab('tab-liste-portes');
  });
  const index = await page.$$eval(BARRE, (boutons, attendu) =>
    boutons.findIndex(b => b.textContent.replace(/\s+/g, ' ').trim() === attendu), libelle);
  assert.ok(index >= 0, `bouton « ${libelle} » absent de la barre`);
  const bouton = page.locator(BARRE).nth(index);
  const [popup] = await Promise.all([context.waitForEvent('page', { timeout: 10000 }), bouton.click()]);
  await popup.waitForLoadState('load');
  return popup;
}

// Tableaux du document : lignes de cellules { texte, th, colspan }.
async function lireTableaux(popup) {
  return popup.evaluate(() => [...document.querySelectorAll('table')].map(table =>
    [...table.querySelectorAll('tr')].map(tr => [...tr.children].map(cellule => ({
      texte: cellule.textContent.replace(/\s+/g, ' ').trim(),
      th: cellule.tagName === 'TH',
      colspan: cellule.colSpan || 1,
    })))));
}

const textes = ligne => ligne.map(c => c.texte);

// Lignes de donnees du tableau dont une ligne d'en-tete commence par `debut`.
function tableauSous(tableaux, debut) {
  for (const lignes of tableaux) {
    const i = lignes.findIndex(l => debut.every((t, k) => textes(l)[k] === t));
    if (i >= 0) return { entete: textes(lignes[i]), lignes: lignes.slice(i + 1).map(textes) };
  }
  return null;
}

// Texte rendu (casse CSS appliquee), espaces normalises.
async function texteRendu(popup) {
  return (await popup.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
}

const nombre = valeur => (['', '-'].includes(valeur) ? 0 : Number(valeur));

// Categorie d'un cable telle que le plan la definit (independante de l'application).
function categorieAttendue(type) {
  const t = String(type || '');
  if (/SSI|CR1/i.test(t)) return 'SSI';
  if (/GTC/i.test(t)) return 'GTC';
  if (/R2V|U1000|H07|CFO/i.test(t)) return 'CFO';
  return 'CFA';
}

// ── Liste de porte ───────────────────────────────────────────────────────

test('L1 barre de la liste des portes : Importer, Exporter Excel, Liste de porte, Carnet de câble, Créer une porte', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const libelles = await page.$$eval(BARRE, boutons => boutons.map(b => b.textContent.replace(/\s+/g, ' ').trim()));
    assert.deepEqual(libelles, ['Importer Excel', 'Exporter Excel', '🖨 Liste de porte', '🖨 Carnet de câble', '+ Créer une porte']);
    assert.ok(!libelles.includes('Export PDF'), 'plus de bouton « Export PDF »');
    const popup = await cliquerBarre(context, page, '🖨 Liste de porte');
    assert.match(await texteRendu(popup), /LISTE DE PORTES/, 'le bouton ouvre la liste de portes');
  });
});

test('L2 liste de porte : A4 portrait marges 0.5in, titre, sous-titre du projet, logo charge', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 portrait;\s*margin:\s*0\.5in/, '@page A4 portrait, marges 0.5in');
    assert.ok(!/A4 landscape/.test(html), 'aucune regle A4 paysage');
    const texte = await texteRendu(popup);
    assert.match(texte, /LISTE DE PORTES/);
    assert.ok(texte.includes('PROJET LE PHOCEA - TERTIAIRE'), `sous-titre « PROJET LE PHOCEA - TERTIAIRE » absent : ${texte.slice(0, 300)}`);
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('L3 liste de porte : encadres BATIMENT (batiments des portes actives), N° PROJET, RESEAUX CONCERNES', OPTIONS, async () => {
  await avecPage(fx.fixtureDeuxBatiments(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const texte = await texteRendu(popup);
    assert.match(texte, /BATIMENT\s*:\s*BATIMENT A \/ B/, `encadre batiment : ${texte.slice(0, 400)}`);
    assert.match(texte, /N° PROJET\s*:\s*P-2026-017/, 'encadre numero de projet');
    assert.match(texte, /RESEAUX CONCERNES\s*:\s*SURETE/, 'encadre reseaux concernes');
  });
});

test('L4 liste de porte : trois sections et leurs en-tetes', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const texte = await texteRendu(popup);
    const titres = ['IDENTIFICATION DES PORTES ET VERROUILLAGE', 'LECTEURS', 'PROGRAMMATION ET COFFRETS'];
    const positions = titres.map(t => texte.indexOf(t));
    positions.forEach((p, i) => assert.ok(p >= 0, `section « ${titres[i]} » absente`));
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b), 'ordre des sections');
    const tableaux = await lireTableaux(popup);
    [
      ['Bâtiment', 'Etage', 'N°Porte', 'Désignation', 'Type de porte', 'Menuiserie', 'Verrouillage'],
      ['N°Porte', 'Entrée', 'Sortie', 'BP', 'DM', 'Barre anti panique'],
      ['N°Porte', 'Coffret', 'Tillys', 'ML'],
    ].forEach(entete => {
      const tableau = tableauSous(tableaux, entete);
      assert.ok(tableau, `en-tete ${entete.join(' | ')} absent`);
      assert.deepEqual(tableau.entete, entete);
      assert.equal(tableau.lignes.length, 4, `${entete.join(' | ')} : une ligne par porte active (1, 2, 3, 10)`);
    });
  });
});

test('L5 liste de porte : identification et lecteurs, vides « - », BP / DM / BAP « 1 » ou « - »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const tableaux = await lireTableaux(popup);
    const tout = tableaux.flat(2).map(c => c.texte).join(' ');
    assert.ok(!tout.includes('—'), 'aucun tiret cadratin dans les tableaux');

    const identification = tableauSous(tableaux, ['Bâtiment', 'Etage', 'N°Porte']);
    assert.ok(identification, 'tableau d\'identification absent');
    const porte1 = identification.lignes.find(l => l[2] === '1');
    assert.ok(porte1, 'porte 1 absente de l\'identification');
    assert.deepEqual(porte1.slice(0, 4), ['A', 'N0', '1', 'Local Velos']);
    assert.equal(porte1[5], '-', 'menuiserie non renseignee : « - »');
    assert.match(porte1[6].normalize('NFD').replace(/[̀-ͯ]/g, ''), /^ventouse$/i, 'verrouillage de la porte 1');

    const lecteurs = tableauSous(tableaux, ['N°Porte', 'Entrée', 'Sortie']);
    assert.ok(lecteurs, 'tableau des lecteurs absent');
    const ligne = num => lecteurs.lignes.find(l => l[0] === num);
    assert.deepEqual(ligne('1'), ['1', 'LB', '-', '1', '1', '-'], 'porte 1 : BP et DM poses');
    assert.deepEqual(ligne('2'), ['2', 'LB', 'LB', '-', '-', '-'], 'porte 2 : lecteur de sortie');
    assert.deepEqual(ligne('3'), ['3', 'LB', '-', '-', '-', '-'], 'porte 3 : rien de pose');
  });
});

test('L6 liste de porte : programmation, ML sans nom de Tillys, relais MLR8 « MLR8 A9 – R3 »', OPTIONS, async () => {
  await avecPage(fx.fixtureMlr8Commande(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    const programmation = tableauSous(await lireTableaux(popup), ['N°Porte', 'Coffret', 'Tillys', 'ML']);
    assert.ok(programmation, 'tableau de programmation absent');
    const ligne = num => programmation.lignes.find(l => l[0] === num) || [];
    assert.deepEqual(ligne('1'), ['1', 'COFFRET 1', 'Tillys 1', 'MLP2 A1']);
    assert.equal(ligne('2')[3], 'MLP2 A3');
    assert.equal(ligne('4')[3], 'MLR8 A9 – R3', 'porte 4 commande seule : relais du MLR8 (tiret U+2013)');
    assert.equal(ligne('10')[3], '-', 'porte 10 orpheline : « - »');
    assert.ok(!programmation.lignes.some(l => l.join(' ').includes('(Tillys')), 'pas de « (Tillys 1) » dans la colonne ML');
  });
});

test('L7 liste de porte : repartition des portes par batiment (Autres si non nul, orphelines comptees)', OPTIONS, async () => {
  const lireRepartition = async popup => {
    assert.match(await texteRendu(popup), /Répartition des Portes par Bâtiment/i, 'encadre de repartition absent');
    const tableau = tableauSous(await lireTableaux(popup), ['Bâtiment', 'Gâche']);
    assert.ok(tableau, 'tableau de repartition absent');
    const lignes = Object.fromEntries(tableau.lignes.map(l => [l[0], l.slice(1).map(nombre)]));
    return { entete: tableau.entete, lignes };
  };

  // Deux batiments : la porte 6 ALIGATOR ouvre la colonne Autres.
  await avecPage(fx.fixtureDeuxBatiments(TIL), async ({ context, page }) => {
    const r = await lireRepartition(await capturerPopup(context, page, () => exporterListePortesPdf()));
    assert.deepEqual(r.entete, ['Bâtiment', 'Gâche', 'Ventouses', 'KEL', 'Cmd', 'Autres', 'Total Bâtiment']);
    assert.deepEqual(r.lignes['Bâtiment A'], [1, 2, 1, 0, 0, 4], 'batiment A : 1 gache, 2 ventouses (dont la porte 10 orpheline), 1 KEL');
    assert.deepEqual(r.lignes['Bâtiment B'], [0, 0, 0, 1, 1, 2], 'batiment B : 1 CMD, 1 ALIGATOR');
    assert.deepEqual(r.lignes['Total GENERAL'], [1, 2, 1, 1, 1, 6]);
  });

  // Sans autre verrouillage : pas de colonne Autres ; porte sans batiment => batiment du projet.
  const t = fx.fixtureBase(TIL);
  t.portes[9].batiment = '';
  await avecPage(t, async ({ context, page }) => {
    const r = await lireRepartition(await capturerPopup(context, page, () => exporterListePortesPdf()));
    assert.deepEqual(r.entete, ['Bâtiment', 'Gâche', 'Ventouses', 'KEL', 'Cmd', 'Total Bâtiment']);
    assert.deepEqual(r.lignes['Bâtiment A'], [1, 1, 1, 0, 3]);
    assert.deepEqual(r.lignes['Bâtiment TERTIAIRE'], [0, 1, 0, 0, 1], 'porte 10 sans batiment : batiment du projet');
    assert.deepEqual(r.lignes['Total GENERAL'], [1, 2, 1, 0, 4]);
  });
});

// ── Carnet de cable ──────────────────────────────────────────────────────

test('K1 bouton « 🖨 Carnet de câble » : A4 paysage marges 0.5in, titre, sous-titre, logo', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await cliquerBarre(context, page, '🖨 Carnet de câble');
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 landscape;\s*margin:\s*0\.5in/, '@page A4 paysage, marges 0.5in');
    assert.ok(!/A4 portrait/.test(html), 'aucune regle A4 portrait');
    const texte = await texteRendu(popup);
    assert.match(texte, /CARNET DE CABLE GENERAL/);
    assert.ok(texte.includes('PROJET LE PHOCEA - TERTIAIRE'), 'sous-titre du projet');
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('K2 carnet de cable : encadres BATIMENT, N° PROJET, RESEAUX CONCERNES', OPTIONS, async () => {
  await avecPage(fx.fixtureDeuxBatiments(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    const texte = await texteRendu(popup);
    assert.match(texte, /BATIMENT\s*:\s*BATIMENT A \/ B/);
    assert.match(texte, /N° PROJET\s*:\s*P-2026-017/);
    assert.match(texte, /RESEAUX CONCERNES\s*:\s*SURETE/);
  });
});

test('K3 carnet de cable : deux lignes d\'en-tete (INFORMATIONS GENERALS / TENANT / ABOUTISSANT)', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    const tableaux = await lireTableaux(popup);
    const tableau = tableaux.find(lignes => lignes.some(l => textes(l)[0] === 'INFORMATIONS GENERALS'));
    assert.ok(tableau, 'tableau du carnet absent');
    const i = tableau.findIndex(l => textes(l)[0] === 'INFORMATIONS GENERALS');
    assert.deepEqual(tableau[i].map(c => [c.texte, c.colspan]), [['INFORMATIONS GENERALS', 4], ['TENANT', 2], ['ABOUTISSANT', 2]]);
    assert.deepEqual(textes(tableau[i + 1]), ['BATIMENT', 'EQUIPEMENT', 'TYPE CABLE', 'REPERE', 'DEPUIS', 'ETAGE', 'VERS', 'ETAGE']);
  });
});

test('K4 carnet de cable : une ligne par cable, colonnes de buildCarnetCableRows, vides « - »', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const attendues = await page.evaluate(() => buildCarnetCableRows().map(r =>
      [r.batiment, r.equipementDepart, r.typeCableDepart, r.codeDepart, r.depart, r.etageDepart, r.arrivee, r.etageArrivee]
        .map(v => String(v || '').trim() || '-')));
    assert.ok(attendues.length >= 5, 'precondition : plusieurs cables dans la fixture');
    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    const lignes = tableauSous(await lireTableaux(popup), ['BATIMENT', 'EQUIPEMENT', 'TYPE CABLE']);
    assert.ok(lignes, 'tableau du carnet absent');
    assert.deepEqual(lignes.lignes, attendues);
    assert.ok(!lignes.lignes.flat().includes('—'), 'aucun tiret cadratin');
  });
});

test('K5 carnet de cable : lignes zebrees', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    const fonds = await popup.evaluate(() => {
      const table = [...document.querySelectorAll('table')].find(t => t.textContent.includes('INFORMATIONS GENERALS'));
      if (!table) return null;
      const lignes = [...table.querySelectorAll('tr')].filter(tr => tr.querySelectorAll('td').length >= 8);
      const fond = el => {
        const td = getComputedStyle(el.querySelector('td')).backgroundColor;
        return td && td !== 'rgba(0, 0, 0, 0)' ? td : getComputedStyle(el).backgroundColor;
      };
      return lignes.slice(0, 4).map(fond);
    });
    assert.ok(fonds, 'tableau du carnet absent');
    assert.ok(fonds.length >= 3, 'precondition : au moins 3 lignes de cable');
    assert.notEqual(fonds[0], fonds[1], `lignes 1 et 2 de meme fond : ${fonds.join(' / ')}`);
    assert.equal(fonds[0], fonds[2], `lignes 1 et 3 de fonds differents : ${fonds.join(' / ')}`);
  });
});

test('K6 getCategorieCableCarnet : SSI, puis GTC, puis CFO, sinon CFA', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const cas = ['CR1 C1 2x1,5', 'Câble SSI 2x1,5', 'CR1 R2V 3G1,5', 'GTC bus', 'GTC sur R2V', 'R2V 2,5mm2', 'U1000 R2V',
      'H07RN-F', 'Cable CFO', 'Cat 6/6A/7', "Cable d'alarme 6x0,22", 'AWG20 3P 9/10', 'Cable KEL', '', 'ssi minuscule'];
    const obtenu = await page.evaluate(types => (typeof getCategorieCableCarnet === 'function'
      ? types.map(t => getCategorieCableCarnet(t)) : null), cas);
    assert.ok(obtenu, 'getCategorieCableCarnet doit etre une fonction globale de la page');
    assert.deepEqual(obtenu, cas.map(categorieAttendue));
  });
});

test('K7 carnet de cable : repartition des cables par type et par batiment', OPTIONS, async () => {
  await avecPage(fx.fixtureDeuxBatiments(TIL), async ({ context, page }) => {
    const rows = await page.evaluate(() => {
      // Un cable de puissance pour avoir au moins une ligne CFO.
      APP.tillys[0].portes[0].cableConfig.lock.type = 'R2V 1,5mm2';
      return buildCarnetCableRows().map(r => ({ batiment: r.batiment, type: r.typeCableDepart }));
    });
    const attendu = {};
    rows.forEach(r => {
      const cle = `Bâtiment ${String(r.batiment || '').trim() || '-'}`;
      attendu[cle] = attendu[cle] || { CFO: 0, CFA: 0, GTC: 0, SSI: 0 };
      attendu[cle][categorieAttendue(r.type)] += 1;
    });
    assert.ok(Object.values(attendu).some(c => c.CFO > 0) && Object.keys(attendu).length === 2, 'precondition : CFO et deux batiments');

    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    assert.match(await texteRendu(popup), /Répartition des Câbles par Type et Bâtiment/i, 'encadre de repartition absent');
    const tableau = tableauSous(await lireTableaux(popup), ['Bâtiment', 'Câbles CFO']);
    assert.ok(tableau, 'tableau de repartition des cables absent');
    assert.deepEqual(tableau.entete, ['Bâtiment', 'Câbles CFO', 'Câbles CFA', 'Câbles GTC', 'Câbles SSI', 'Total Bâtiment']);
    const lignes = Object.fromEntries(tableau.lignes.map(l => [l[0], l.slice(1).map(nombre)]));
    Object.entries(attendu).forEach(([cle, c]) => {
      assert.deepEqual(lignes[cle], [c.CFO, c.CFA, c.GTC, c.SSI, c.CFO + c.CFA + c.GTC + c.SSI], cle);
    });
    assert.equal(lignes['Total GENERAL'][4], rows.length, 'Total GENERAL = nombre de cables');
  });
});

test('K8 carnet de cable : « Exporter Excel » appelle l\'export de la page ; aucune fenetre sans cable', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    await page.evaluate(() => {
      window.__exportsCarnet = 0;
      window.exporterCarnetCableExcel = () => { window.__exportsCarnet += 1; };
    });
    const popup = await capturerPopup(context, page, () => imprimerCarnetCable());
    const bouton = popup.locator('button', { hasText: 'Exporter Excel' });
    assert.equal(await bouton.count(), 1, 'bouton « Exporter Excel » absent de la fenetre du carnet');
    await bouton.click();
    assert.equal(await page.evaluate(() => window.__exportsCarnet), 1, 'exporterCarnetCableExcel de la page non appele');
  });
  await avecPage(fx.fixtureSansPorteActive(TIL), async ({ context, page }) => {
    const ouvertes = [];
    context.on('page', p => ouvertes.push(p));
    await page.evaluate(() => imprimerCarnetCable());
    await page.waitForTimeout(500);
    assert.equal(ouvertes.length, 0, 'aucune fenetre attendue sans cable');
  });
});
