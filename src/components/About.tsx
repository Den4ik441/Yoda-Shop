import React from 'react';
import { Laptop, Briefcase, Award, Coffee } from 'lucide-react';

const About = () => {
  return (
    <section id="about" className="py-20 px-6 md:px-8 bg-secondary/30">
      <div className="max-w-7xl mx-auto">
        <div className="text-center mb-16 opacity-0 animate-slide-up">
          <h2 className="section-heading">About Me</h2>
          <p className="section-subheading max-w-2xl mx-auto">
            Professional programmer and digital service provider
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          <div className="opacity-0 animate-slide-up">
            <div className="glass-panel p-8 aspect-square relative">
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-2/3 h-2/3 rounded-full bg-yoda-green/10 flex items-center justify-center">
                  <Laptop size={128} className="text-yoda-green/70" />
                </div>
              </div>
              
              {/* Stats */}
              <div className="absolute bottom-8 left-8 right-8">
                <div className="glass-panel p-4 grid grid-cols-3 gap-4 text-center">
                  {[
                    { icon: <Briefcase size={18} />, value: "5+", label: "Years Exp." },
                    { icon: <Award size={18} />, value: "100+", label: "Projects" },
                    { icon: <Coffee size={18} />, value: "1,000+", label: "Clients" },
                  ].map((stat, index) => (
                    <div key={index} className="flex flex-col items-center gap-1">
                      <div className="text-yoda-green">
                        {stat.icon}
                      </div>
                      <div className="font-bold text-lg">{stat.value}</div>
                      <div className="text-xs text-muted-foreground">{stat.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
          
          <div className="space-y-6 opacity-0 animate-slide-up delay-200">
            <h3 className="text-2xl font-medium">Professional Programmer & Service Provider</h3>
            <p className="text-muted-foreground">
              I'm a dedicated professional with expertise in programming and digital services. Through my shop, Yoda Shop YS, I provide premium digital solutions including ininal services, Stars Telegram Premium, and custom programming solutions.
            </p>
            
            <div className="space-y-4 pt-4">
              {[
                {
                  title: "Expertise in Programming",
                  description: "With years of experience in software development, I create custom solutions tailored to client needs."
                },
                {
                  title: "Digital Service Provider",
                  description: "Offering premium digital services including ininal and Telegram-related solutions."
                },
                {
                  title: "Customer-Centric Approach",
                  description: "I prioritize understanding client requirements to deliver the best possible solutions."
                }
              ].map((item, index) => (
                <div key={index} className="opacity-0 animate-fade-in" style={{ animationDelay: `${(index + 3) * 100}ms` }}>
                  <h4 className="text-lg font-medium">{item.title}</h4>
                  <p className="text-muted-foreground text-sm">{item.description}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
};

export default About;
