import React from 'react';
import { ArrowRight, ShoppingBag, Send, Code } from 'lucide-react';

const Hero = () => {
  return (
    <section id="home" className="min-h-screen pt-24 pb-16 px-6 md:px-8 flex items-center relative overflow-hidden gradient-bg">
      <div className="max-w-7xl mx-auto w-full">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          <div className="space-y-6 opacity-0 animate-slide-up">
            <div className="inline-block px-3 py-1 rounded-full bg-primary/10 text-primary text-sm font-medium">
              Premium Digital Services
            </div>
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold leading-tight">
              Welcome to <span className="text-yoda-green">Yoda Shop YS</span>
            </h1>
            <p className="text-lg md:text-xl text-muted-foreground max-w-xl">
              Your trusted provider of digital services including ininal, Stars Telegram Premium, and professional programming solutions.
            </p>
            <div className="flex flex-wrap gap-4 pt-4">
              <a 
                href="#services" 
                className="flex items-center gap-2 px-6 py-3 bg-primary text-white rounded-full font-medium hover:bg-primary/90 transition-colors"
              >
                Explore Services <ArrowRight size={18} />
              </a>
              <a 
                href="#contact" 
                className="flex items-center gap-2 px-6 py-3 border border-foreground/20 rounded-full font-medium hover:bg-foreground/5 transition-colors"
              >
                Contact Us
              </a>
            </div>
          </div>
          
          <div className="relative opacity-0 animate-slide-up delay-300">
            <div className="glass-panel p-8 md:p-10 relative z-10 opacity-0 animate-fade-in delay-400">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-6">
                {[
                  { icon: <ShoppingBag className="text-yoda-green" size={32} />, title: "ininal" },
                  { icon: <Send className="text-yoda-green" size={32} />, title: "Telegram" },
                  { icon: <Code className="text-yoda-green" size={32} />, title: "Programming" },
                ].map((service, index) => (
                  <div 
                    key={index}
                    className="flex flex-col items-center text-center gap-3 opacity-0 animate-fade-in"
                    style={{ animationDelay: `${(index + 5) * 100}ms` }}
                  >
                    <div className="w-16 h-16 rounded-full bg-secondary flex items-center justify-center animate-float">
                      {service.icon}
                    </div>
                    <span className="font-medium">{service.title}</span>
                  </div>
                ))}
              </div>
            </div>
            
            {/* Decorative elements */}
            <div className="absolute w-64 h-64 rounded-full bg-primary/5 -top-10 -right-10 animate-pulse-subtle"></div>
            <div className="absolute w-40 h-40 rounded-full bg-primary/10 -bottom-5 -left-5 animate-pulse-subtle" style={{ animationDelay: '1s' }}></div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default Hero;
