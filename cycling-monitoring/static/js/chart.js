const margin = {top: 20, right: 30, bottom: 30, left: 60},
    width = 900 - margin.left - margin.right,
    height = 400 - margin.top - margin.bottom;

const parseTime = d3.timeParse("%m/%d/%Y");
const dateFormat = d3.timeFormat("%m/%d/%Y");

const x = d3.scaleTime()
    .range([0, width]);

const y = d3.scaleLinear()
    .range([height, 0]);

         // define the line
         var line = d3.line()
            .x(function(d) { console.log(d.date);return x(d.date); })
            .y(function(d) { console.log(d.speed); return y(d.speed); });


const svg = d3.select("#chart").append("svg")
    .attr("id", "svg")
    .attr("width", width + margin.left + margin.right)
    .attr("height", height + margin.top + margin.bottom)
    .append("g")
    .attr("transform", "translate(" + margin.left + "," + margin.top + ")");


var data = [
{"date":"08/19/2020","speed" : 23.5},
{"date":"09/22/2020","speed" : 25},
{"date":"10/01/2020", "speed" :27.5},
{"date":"10/01/2020", "speed" :28.5}
]

    // Conversion des données du fichier, parsing des dates et '+' pour expliciter une valeur numérique.
    data.forEach(function(d) {
        d.date = parseTime(d.date);
       // d.speed = d.speed
    });
    
    // Contrairement au tutoriel Bar Chart, plutôt que de prendre un range entre 0 et le max on demande 
    // directement à D3JS de nous donner le min et le max avec la fonction 'd3.extent', pour la date comme 
    // pour le cours de fermeture (close).
    x.domain(d3.extent(data, d => d.date));
    y.domain(d3.extent(data, d => d.speed));

    // Ajout de l'axe X
    svg.append("g")
        .attr("transform", "translate(0," + height + ")")
        .call(d3.axisBottom(x));
    
    // Ajout de l'axe Y et du texte associé pour la légende
    svg.append("g")
        .call(d3.axisLeft(y))
        .append("text")
            .attr("fill", "#000")
            .attr("transform", "rotate(-90)")
            .attr("y", 6)
            .attr("dy", "0.71em")
            .style("text-anchor", "end")
            .text("speed");
    

      svg
    .append('defs')
    .append('marker')
    .attr('id', 'dot')
    .attr('viewBox', [0, 0, 20, 20])
    .attr('refX', 10)
    .attr('refY', 10)
    .attr('markerWidth', 5)
    .attr('markerHeight', 5)
    .append('circle')
    .attr('cx', 10)
    .attr('cy', 10)
    .attr('r', 10)
    .style('fill', 'green');

 
    // Ajout d'un path calculé par la fonction line à partir des données de notre fichier.
    svg.append("path")
        .datum(data)
        .attr("class", "line")
        .attr("d", line)
        .attr("fill", "none")
        .attr("stroke", "blue")
        .attr("stroke-width", 2)
        .attr('marker-start', 'url(#dot)')
    .attr('marker-mid', 'url(#dot)')
    .attr('marker-end', 'url(#dot)');

