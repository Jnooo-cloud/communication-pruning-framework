// Structural diagnostics only. Never print input text, answers, or predictions.
import fs from 'node:fs';
import readline from 'node:readline';
import crypto from 'node:crypto';
import path from 'node:path';
const base = 'archive/neustart-2026-08-30/legacy-artifact/eval-harness/data/vendor/musique-v1.0/data';
const normalize = s => s.toLowerCase().replace(/[^a-z0-9]/g, '');
// Public Table 1 questions appeared in the literature retrieval. Check exposure by exact normalized question.
const publicExamples = new Set([
  'Who succeeded the first President of Namibia?',
  'What currency is used where Billy Giles died?',
  'When was the first establishment that McDonaldization is named after, open in the country Horndean is located?',
  'When did Napoleon occupy the city where the mother of the woman who brought Louis XVI style to the court died?',
  'How many Germans live in the colonial holding in Aruba’s continent that was governed by Prazeres’s country?',
  'When did the people who captured Malakoff come to the region where Philipsburg is located?',
].map(normalize));
const trainParagraphs = new Set(), trainSupportParagraphs = new Set(), inventory = {}, matches = [];
const percentile = (sorted,q) => sorted[Math.floor((sorted.length-1)*q)];
for (const split of ['train','dev']) {
  const paragraphCounts = {}, chars = [];
  let sharedTasks=0, sharedOccurrences=0, tasks=0, devSupportInTrainAny=0, devSupportInTrainSupport=0;
  for await (const line of readline.createInterface({input:fs.createReadStream(path.join(base,`musique_ans_v1.0_${split}.jsonl`)),crlfDelay:Infinity})) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    if (publicExamples.has(normalize(row.question))) matches.push({split,id:row.id});
    if (!Array.isArray(row.paragraphs)) throw new Error('Unexpected paragraph schema');
    paragraphCounts[row.paragraphs.length] = (paragraphCounts[row.paragraphs.length]||0)+1;
    let charCount = 0, shared=false;
    for(const p of row.paragraphs) {
      if(typeof p.paragraph_text !== 'string')throw new Error('Unexpected paragraph text schema');
      charCount += p.paragraph_text.length + (p.title||'').length;
      const hash = crypto.createHash('sha256').update(p.paragraph_text.trim().replace(/\s+/g,' ')).digest('hex');
      if(split==='train') {
        trainParagraphs.add(hash);
        if(p.is_supporting)trainSupportParagraphs.add(hash);
      } else {
        if(trainParagraphs.has(hash)){shared=true;sharedOccurrences++;if(p.is_supporting)devSupportInTrainAny++;}
        if(p.is_supporting && trainSupportParagraphs.has(hash))devSupportInTrainSupport++;
      }
    }
    chars.push(charCount);
    sharedTasks += Number(shared);
    tasks++;
  }
  chars.sort((a,b)=>a-b);
  inventory[split] = {tasks,paragraphCounts,contextCharactersIncludingTitles:{min:chars[0],p50:percentile(chars,.5),p90:percentile(chars,.9),p95:percentile(chars,.95),max:chars.at(-1)},
    ...(split==='dev'?{tasksWithExactWhitespaceNormalizedParagraphInTrain:sharedTasks,sharedParagraphOccurrences:sharedOccurrences,
      devSupportingParagraphOccurrencesAlsoInTrainAny:devSupportInTrainAny,devSupportingParagraphOccurrencesAlsoInTrainSupport:devSupportInTrainSupport}: {})};
}
console.log(JSON.stringify({structuralOnly:true,tokenCountsNotMeasured:true,publicPaperTable1ExactQuestionMatches:matches,
  scope:'All official train/dev records, before exposure exclusion. Public-example check is exact normalized text, not semantic equivalence.',inventory},null,2));
