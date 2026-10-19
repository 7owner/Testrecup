'use strict';

// Tests de bout en bout de app/index.html dans Chromium (Playwright), contre le
// serveur local du projet sur un port libre. Plan « Logiciel TIL » : E0 a E11.
// Aucune impression reelle (window.print neutralise), aucun export Excel.
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { chargerGenerator } = require('./helpers/charger-generator');
const fx = require('./helpers/fixtures');
const { demarrerApp, preparerPage, capturerPopup, largeurImage } = require('./helpers/page');

const TIL = chargerGenerator();
const OPTIONS = { timeout: 30000 };
const LOGO = 'img[src*="logo-fauche-digital.png"]';

let app;
before(async () => { app = await demarrerApp(); });
after(async () => { if (app) await app.fermer(); });

// Ouvre un contexte neuf avec la fixture, execute le scenario, ferme toujours.
async function avecPage(tillys, scenario) {
  const session = await preparerPage(app, tillys);
  try {
    return await scenario(session);
  } finally {
    await session.context.close();
  }
}

test('E0 (non-regression) aucune erreur de page au chargement et a l\'injection de la fixture', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page, erreurs }) => {
    await page.waitForTimeout(300);
    assert.deepEqual(erreurs.map(e => e.message), []);
  });
});

test('E1 en-tetes du tableau d\'adresses : vocabulaire terrain', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const entetes = await page.$$eval('#addr-table thead th', ths => ths.map(th => th.textContent.trim()));
    const attendus = ['Relais', 'LED Verte', 'LED Rouge', 'Buzzer', 'BP', 'Etat Porte', 'DM', 'AP Boite CA'];
    const positions = attendus.map(libelle => entetes.indexOf(libelle));
    positions.forEach((pos, i) => assert.ok(pos >= 0, `en-tete « ${attendus[i]} » absent : ${entetes.join(' | ')}`));
    assert.deepEqual(positions, [...positions].sort((a, b) => a - b), `ordre des en-tetes : ${entetes.join(' | ')}`);
    ['Lock', 'LED+', 'LED-', 'Capteur'].forEach(ancien => {
      assert.ok(!entetes.includes(ancien), `ancien en-tete « ${ancien} » encore present`);
    });
  });
});

test('E2 tableau d\'adresses rendu : equipements poses, ligne du lecteur de sortie, serrures', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const lignes = await page.evaluate(() => {
      renderTableauAdresses();
      return [...document.querySelectorAll('#addr-tbody tr')]
        .map(tr => [...tr.querySelectorAll('td')].map(td => td.textContent.replace(/\s+/g, ' ').trim()));
    });
    assert.equal(lignes.length, 25, '24 portes + 1 ligne de lecteur de sortie');

    const indexPorte = num => lignes.findIndex(cellules => cellules[0] === String(num).padStart(2, '0'));
    const porte1 = lignes[indexPorte(1)];
    assert.equal(porte1[12], 'DA0101', 'porte 1 : BP');
    assert.equal(porte1[14], 'DA0103', 'porte 1 : DM');
    assert.equal(porte1[15], '—', 'porte 1 : pas d\'AP');

    const porte3 = lignes[indexPorte(3)];
    assert.equal(porte3[12], '—', 'porte 3 : pas de BP');
    assert.equal(porte3[16], 'M2', 'porte 3 : commande hyperviseur');
    assert.equal(porte3[17], 'TN2', 'porte 3 : timer');

    const i2 = indexPorte(2);
    const sortie = (lignes[i2 + 1] || []).join(' | ');
    ['LA4', 'Lecteur de sortie', 'XA0306', 'XA0307', 'XA0308'].forEach(valeur => {
      assert.ok(sortie.includes(valeur), `ligne suivant la porte 2 sans « ${valeur} » : ${sortie}`);
    });

    assert.equal(lignes[i2][7], '🔒 KEL', 'serrure porte 2');
    assert.equal(porte3[7], '🔒 GÂCHE', 'serrure porte 3');
  });
});

test('E3 labelSerrure : libelles des verrouillages', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const libelles = await page.evaluate(() => ({
      kel: labelSerrure('KEL'),
      gacheMaj: labelSerrure('GACHE'),
      gacheMin: labelSerrure('gache'),
      aperio: labelSerrure('APERIO'),
      cmd: labelSerrure('CMD'),
      vide: labelSerrure(''),
      indefini: labelSerrure(undefined),
      ventouse: labelSerrure('VENTOUSE'),
    }));
    assert.deepEqual(libelles, {
      kel: '🔒 KEL',
      gacheMaj: '🔒 GÂCHE',
      gacheMin: '🔒 GÂCHE',
      aperio: 'APERIO',
      cmd: 'CMD',
      vide: '—',
      indefini: '—',
      ventouse: '🧲 VENTOUSE',
    });
  });
});

test('E4 export CSV : en-tete, ligne de sortie, BP/DM/AP vides, voies MLR8 et MLIO', OPTIONS, async () => {
  await avecPage(fx.fixtureModulesTerrain(TIL), async ({ page }) => {
    const csv = await page.evaluate(() => {
      window.__csv = null;
      window.telechargerContenu = contenu => { window.__csv = contenu; };
      exporterCSV();
      return window.__csv;
    });
    assert.equal(typeof csv, 'string', 'exporterCSV doit produire un contenu');
    const lignes = csv.split(/\r?\n/).filter(Boolean).map(l => l.split(';'));
    assert.equal(lignes[0].join(';'),
      'TriNum;PorteApp;ID;Bus;Carte;Lecteur;Description;Mode;Serrure;Relais;LED Verte;LED Rouge;Buzzer;BP;Etat Porte;DM;AP Boite CA;CmdHyper;Timer;Effraction;POTL');

    const i2 = lignes.findIndex(c => c[1] === '2');
    const sortie = lignes[i2 + 1] || [];
    assert.equal(sortie[5], 'LA4', 'lecteur de sortie de la porte 2');
    assert.equal(sortie[6], '"Hall - sortie"');
    assert.deepEqual(sortie.slice(10, 13), ['XA0306', 'XA0307', 'XA0308']);

    const porte3 = lignes.find(c => c[1] === '3');
    assert.deepEqual([porte3[13], porte3[15], porte3[16]], ['', '', ''], 'porte 3 : BP, DM, AP vides');

    const mlr8 = lignes.find(c => c[0] === 'MLR8 A9 R1');
    assert.ok(mlr8, 'voie R1 du MLR8 A9 absente du CSV');
    assert.equal(mlr8[9], 'XA0901', 'registre MLR8 en colonne Relais');
    const mlio = lignes.find(c => c[0] === 'MLIO A10 I1');
    assert.ok(mlio, 'voie I1 du MLIO A10 absente du CSV');
    assert.equal(mlio[lignes[0].indexOf('BP')], 'DA1001', 'registre MLIO en colonne BP');
  });
});

test('E5 etiquettes chantier des lecteurs dans le synoptique', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const resultat = await page.evaluate(() => {
      const t = APP.tillys[0];
      const ma1 = t.synopticModules.find(m => m.id === 'MA1');
      const ma3 = t.synopticModules.find(m => m.id === 'MA3');
      const meta = html => {
        const tpl = document.createElement('template');
        tpl.innerHTML = html;
        const el = tpl.content.querySelector('.synoptic-door-meta');
        return { texte: el.textContent.trim(), title: el.getAttribute('title') };
      };
      return {
        avecNumero: getPorteReaderChantierLabels({ lecteurEntree: 'LB', numeroEntree: '001' }, ['LA1']),
        sansNumero: getPorteReaderChantierLabels({ lecteurEntree: 'LB' }, ['LA1']),
        tropDeTetes: getPorteReaderChantierLabels({ lecteurEntree: 'LB', numeroEntree: '001' }, ['LA1', 'LA2']),
        porte1: meta(renderSynopticDoorNode(t, 0, ma1, 1)),
        porte3: meta(renderSynopticDoorNode(t, 0, ma1, 3)),
        porte2: meta(renderSynopticDoorNode(t, 0, ma3, 2)),
      };
    });
    assert.deepEqual(resultat.avecNumero, ['LB001']);
    assert.deepEqual(resultat.sansNumero, ['LA1']);
    assert.deepEqual(resultat.tropDeTetes, ['LA1', 'LA2']);
    assert.equal(resultat.porte1.texte, 'LB001');
    assert.equal(resultat.porte1.title, 'LA1');
    assert.equal(resultat.porte3.texte, 'LA2');
    assert.equal(resultat.porte2.texte, 'LA3 · LA4');
  });
});

test('E6 carnet de cables : avec boite de jonction, CMD/BP/DM partent de la BJ', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    // Lecture seule des lignes calculees : aucun export Excel declenche.
    const lignes = await page.evaluate(() => buildCarnetCableRows()
      .map(r => ({ code: r.codeDepart, depart: r.depart, equipement: r.equipementDepart })));
    const ligne = code => lignes.find(l => l.code === code);

    ['CMD A_N0_1', 'BP A_N0_1', 'DM A_N0_1'].forEach(code => {
      assert.ok(ligne(code), `ligne ${code} absente`);
      assert.equal(ligne(code).depart, 'BJ A_N0_1', `${code} doit partir de la boite de jonction`);
    });

    const bj = ligne('BJ A_N0_1');
    assert.ok(bj, 'ligne BJ A_N0_1 absente');
    assert.match(bj.depart, /Tillys 1/, 'la boite de jonction part du coffret / Tillys');

    const lecteur = ligne('001');
    assert.ok(lecteur, 'ligne du lecteur d\'entree de la porte 1 absente');
    assert.match(lecteur.depart, /Tillys 1/, 'le lecteur d\'entree part du coffret / Tillys');

    const cmd3 = ligne('CMD A_N0_3');
    assert.ok(cmd3, 'ligne CMD A_N0_3 absente');
    assert.match(cmd3.depart, /Tillys 1/, 'porte 3 sans BJ : CMD part du coffret / Tillys');
    assert.ok(!cmd3.depart.startsWith('BJ'), 'porte 3 sans BJ : CMD ne part pas d\'une BJ');
  });
});

test('E7 bandeau des coffrets : plus de compteur d\'elements lies', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const { lies, texte } = await page.evaluate(() => {
      const coffret = getProjectCoffrets()[0];
      const tpl = document.createElement('template');
      tpl.innerHTML = renderCoffretSummaryBar();
      return {
        lies: coffret ? getLinkedCoffretItems(coffret).length : 0,
        texte: tpl.content.textContent.replace(/\s+/g, ' ').trim(),
      };
    });
    assert.ok(lies >= 1, 'precondition : le coffret de la fixture doit avoir un element lie');
    assert.match(texte, /coffret/i);
    // Singulier ou pluriel : « 1 element lie » comme « 2 elements lies ».
    assert.doesNotMatch(texte, /li[ée]s?(?![a-z])/i, `bandeau : ${texte}`);
  });
});

test('E8 plan d\'implantation : A4 paysage, une page par coffret equipe, logo charge', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    const equipes = await page.evaluate(() => getProjectCoffrets()
      .filter(c => Array.isArray(c.configEquipements) && c.configEquipements.length > 0).length);
    assert.ok(equipes >= 1, 'precondition : au moins un coffret avec configEquipements');

    const popup = await capturerPopup(context, page, () => genererPlanImplantationComplet());
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 landscape/);
    assert.ok(!html.includes('A4 portrait'), 'aucune regle A4 portrait');
    assert.equal(await popup.locator('.coffret-print-page').count(), equipes);
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('E9 impression du synoptique coffret : A4 paysage et logo charge', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ context, page }) => {
    await page.evaluate(() => ouvrirCoffretSynoptique(0));
    const svg = await page.locator('#coffret-synoptique-body svg').count();
    assert.ok(svg > 0, 'precondition : le synoptique coffret doit contenir un schema');

    const popup = await capturerPopup(context, page, () => imprimerCoffretSynoptique());
    // La fenetre lance l'impression au chargement : l'appel doit avoir ete intercepte.
    await popup.waitForFunction(() => window.__printAppels >= 1, null, { timeout: 5000 });
    const html = await popup.content();
    assert.match(html, /@page\s*\{\s*size:\s*A4 landscape/);
    assert.ok(!html.includes('A4 portrait'), 'aucune regle A4 portrait');
    assert.ok(await largeurImage(popup, LOGO) > 0, 'logo Fauche non charge');
  });
});

test('E10a bouton « Export PDF » de la liste des portes', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const bouton = page.locator('button[onclick="exporterListePortesPdf()"]');
    assert.equal(await bouton.count(), 1, 'bouton exporterListePortesPdf() absent');
    assert.equal((await bouton.textContent()).trim(), 'Export PDF');
  });
});

test('E10b PDF de reperage, 24 portes : sections, suites, cartouche en bas, pagination', OPTIONS, async () => {
  await avecPage(fx.fixture24Portes(TIL), async ({ context, page }) => {
    const popup = await capturerPopup(context, page, () => exporterListePortesPdf());
    await popup.waitForFunction(() => document.querySelectorAll('.rep-page').length > 0);
    const mesure = await popup.evaluate(() => [...document.querySelectorAll('.rep-page')].map(pageEl => {
      const body = pageEl.querySelector('.rep-body');
      const cartouche = pageEl.querySelector('.rep-cartouche');
      const rectPage = pageEl.getBoundingClientRect();
      const bordBas = parseFloat(getComputedStyle(pageEl).borderBottomWidth) || 0;
      const blocs = [];
      [...body.children].forEach(el => {
        if (el.classList.contains('rep-section-titre')) blocs.push({ titre: el.textContent.trim(), lignes: 0 });
        else if (el.tagName === 'TABLE' && blocs.length) blocs[blocs.length - 1].lignes = el.querySelectorAll('tbody tr').length;
      });
      return {
        scrollHeight: body.scrollHeight,
        clientHeight: body.clientHeight,
        dernier: pageEl.lastElementChild ? pageEl.lastElementChild.className : '',
        basCartouche: cartouche ? cartouche.getBoundingClientRect().bottom : NaN,
        basPage: rectPage.bottom - bordBas,
        meta: (pageEl.querySelector('.rep-meta') || {}).textContent || '',
        blocs,
      };
    }));

    const total = mesure.length;
    assert.ok(total >= 2, `24 portes a designations longues : plusieurs pages attendues, ${total} obtenue(s)`);
    mesure.forEach((p, i) => {
      assert.ok(p.scrollHeight <= p.clientHeight + 1, `page ${i + 1} : contenu deborde (${p.scrollHeight} > ${p.clientHeight})`);
      assert.match(p.dernier, /\brep-cartouche\b/, `page ${i + 1} : le cartouche doit etre le dernier element`);
      assert.ok(Math.abs(p.basCartouche - p.basPage) <= 1, `page ${i + 1} : cartouche decolle du bas (${p.basCartouche} / ${p.basPage})`);
      assert.match(p.meta, new RegExp(`Page ${i + 1}/${total}(?!\\d)`), `page ${i + 1} : pagination`);
    });

    const blocs = mesure.flatMap(p => p.blocs);
    const base = titre => titre.replace(/\s*\(suite\)$/, '');
    const sections = [...new Set(blocs.map(b => base(b.titre)))];
    assert.equal(sections.length, 3, `3 sections attendues : ${sections.join(' | ')}`);
    sections.forEach(section => {
      const siens = blocs.filter(b => base(b.titre) === section);
      assert.ok(!/\(suite\)$/.test(siens[0].titre), `${section} : le premier bloc n'est pas une suite`);
      siens.slice(1).forEach(b => assert.match(b.titre, /\(suite\)$/, `${section} : bloc coupe sans « (suite) »`));
      assert.equal(siens.reduce((s, b) => s + b.lignes, 0), 24, `${section} : 24 lignes au total`);
    });
    assert.ok(blocs.some(b => /\(suite\)$/.test(b.titre)), 'au moins une section coupee attendue avec 24 portes');
  });
});

test('E10c PDF de reperage sans porte active : aucune fenetre ouverte', OPTIONS, async () => {
  await avecPage(fx.fixtureSansPorteActive(TIL), async ({ context, page }) => {
    const ouvertes = [];
    context.on('page', p => ouvertes.push(p));
    await page.evaluate(() => exporterListePortesPdf());
    await page.waitForTimeout(500);
    assert.equal(ouvertes.length, 0, 'aucune popup attendue sans porte active');
  });
});

test('E11 fiche detail porte : lecteur de sortie, registres au numero de lecteur', OPTIONS, async () => {
  await avecPage(fx.fixtureBase(TIL), async ({ page }) => {
    const fiche = async num => page.evaluate(n => {
      voirDetailPorte(n, 0);
      const body = document.getElementById('modal-body');
      const lignes = [...body.querySelectorAll('.detail-row')].map(row => [
        (row.querySelector('.detail-key') || {}).textContent?.trim() || '',
        (row.querySelector('.detail-val') || {}).textContent?.trim() || '',
      ]);
      return {
        sousTitre: document.getElementById('modal-subtitle').textContent.trim(),
        texte: body.textContent.replace(/\s+/g, ' '),
        lignes,
      };
    }, num);

    const p2 = await fiche(2);
    assert.ok(p2.sousTitre.endsWith('LA3 · LA4'), `sous-titre porte 2 : ${p2.sousTitre}`);
    assert.ok(p2.texte.includes('TN3=300'), 'porte 2 : TN3=300 attendu');
    assert.ok(!p2.texte.includes('TN2='), 'porte 2 : TN2= ne doit pas apparaitre');
    ['LED Verte sortie (LA4)', 'XA0306', 'XA0307', 'XA0308'].forEach(valeur => {
      assert.ok(p2.texte.includes(valeur), `porte 2 : « ${valeur} » attendu`);
    });

    const p3 = await fiche(3);
    assert.ok(p3.texte.includes('TN2=300'), 'porte 3 : TN2=300 attendu');
    assert.ok(p3.sousTitre.endsWith('LA2'), `sous-titre porte 3 : ${p3.sousTitre}`);

    const p1 = await fiche(1);
    const valeur = cle => (p1.lignes.find(([k]) => k === cle) || [])[1];
    assert.equal(valeur('Bouton Poussoir'), 'DA0101', 'porte 1 : BP');
    assert.equal(valeur('Déclencheur manuel'), 'DA0103', 'porte 1 : DM');
  });
});
